# Métricas, eventos e deploy (Etapa 4)

## Métricas (Prometheus)

`GET /metrics` é público (sem JWT) e fica fora do OpenAPI. O gateway nginx **não** expõe essa rota;
o Prometheus faz scrape direto em `onboarding-api:8081/metrics` pela rede interna.

| Métrica | Tipo | Labels | Origem |
| ------- | ---- | ------ | ------ |
| `http_requests_total` | counter | `handler`, `method`, `status` (2xx/4xx/5xx) | `prometheus-fastapi-instrumentator` (padrão) |
| `http_request_duration_seconds` | histogram | `handler`, `method` | idem |
| `http_request_duration_highr_seconds` | histogram | — | idem (buckets finos para p95/p99) |
| `customers_created_total` | counter | — | incrementada a cada `POST /customers` com 201 |
| `events_published_total` | counter | `routing_key`, `result` (`ok`/`error`) | publisher RabbitMQ; nada é contado com a mensageria desligada |

Os contadores de negócio ficam em `app/core/metrics.py`, no nível do módulo, para não serem
registrados duas vezes quando o app é criado mais de uma vez (testes).

## Eventos (RabbitMQ)

- `RABBITMQ_URL` (ex.: `amqp://erp:erp@rabbitmq:5672/`). **Vazia = mensageria desligada (no-op)**.
- Exchange `erp.events`, tipo `topic`, durável. Mensagens JSON (`content_type=application/json`), persistentes.
- `EventPublisher` (`app/events/publisher.py`) conecta com `connect_robust` no lifespan; se o broker
  estiver fora, loga e tenta de novo no próximo publish. O router agenda o publish em `BackgroundTasks`
  (depois do commit). **Falha ao publicar nunca quebra a requisição**: loga e conta `result="error"`.

| Routing key | Quando | Payload |
| ----------- | ------ | ------- |
| `customer.created` | após `POST /customers` (201) | `event_id`, `event_type`, `occurred_at`, `customer_id`, `nome`, `cpf`, `email` |
| `customer.anamnesis_updated` | após `PUT /customers/{id}/anamnesis` (200) | `event_id`, `event_type`, `occurred_at`, `customer_id`, `dividas_ativas`, `comprometimento_renda` |

`event_id` é UUID4 e `occurred_at` é ISO-8601 em UTC. Exemplo:

```json
{
  "event_id": "5b0e8d8e-3f4c-4a3e-9d1b-2b5d0f7c9a11",
  "event_type": "customer.created",
  "occurred_at": "2026-11-03T12:00:00.000000+00:00",
  "customer_id": 1,
  "nome": "João da Silva",
  "cpf": "12345678900",
  "email": "joao@example.com"
}
```

## Banco por schema (compose)

No stack do `erp-banking-infra` existe um PostgreSQL `erp` com o schema `onboarding`:

```
DATABASE_URL=postgresql+psycopg://erp:erp@postgres:5432/erp?options=-csearch_path%3Donboarding
```

O `options=-csearch_path=onboarding` é repassado ao libpq pelo psycopg, então o `create_all` do
startup cria as tabelas nesse schema (que precisa existir; o init script do infra cria).

## Atrás do gateway (`ROOT_PATH`)

O nginx publica a API em `/onboarding/...` e remove o prefixo. Com `ROOT_PATH=/onboarding`, o FastAPI
recebe `root_path`, o `/docs` e o `/redoc` apontam para `/onboarding/openapi.json` e o OpenAPI declara
`servers: [{"url": "/onboarding"}]`, então o "Try it out" do Swagger também passa pelo gateway.

## Docker / imagem

- `python:3.13-slim`, usuário não-root (`appuser`), `/app` gravável (SQLite padrão).
- `PORT` (padrão 8081) usado pelo `CMD` e pelo `HEALTHCHECK` (`GET /health` via `urllib`).
- CI: job `publish` (só em push na `main`) envia `ghcr.io/murilozgodoy/erp-banking-onboarding-api:latest`
  e `:<sha>` para o GHCR.

```bash
docker build -t onboarding-api .
docker run --rm -p 8081:8081 --env-file .env onboarding-api
```
