# ERP Banking - Onboarding API

Serviço responsável pelo cadastro de clientes e anamnese financeira.
Contexto do projeto, arquitetura e autenticação em [docs/](docs/README.md).

## Requisitos

- Python 3.11+

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows PowerShell
pip install -r requirements-dev.txt
cp .env.example .env
```

## Executar

```bash
python -m app.main          # http://localhost:8081 (porta configurável por PORT)
```

Docs interativas: http://localhost:8081/docs (exigem Bearer token, ver abaixo).

## Testes com cobertura

```bash
pytest
```

Cobertura mínima exigida: **80%** (falha o build se abaixo). Os testes não precisam de RabbitMQ
(o broker é mockado).

## Docker

```bash
docker build -t onboarding-api .
docker run --rm -p 8081:8081 --env-file .env onboarding-api
```

Imagem `python:3.13-slim`, usuário não-root, `HEALTHCHECK` em `/health` e porta via `PORT`.
Em push na `main` o CI publica `ghcr.io/murilozgodoy/erp-banking-onboarding-api:latest` e `:<sha>`.

## Métricas e eventos

- `GET /metrics`: métricas HTTP padrão (`http_requests_total`, `http_request_duration_seconds`) e de
  negócio (`customers_created_total`, `events_published_total{routing_key,result}`).
- Publica `customer.created` (após `POST /customers`) e `customer.anamnesis_updated` (após
  `PUT /customers/{id}/anamnesis`) na exchange topic `erp.events`. Falha no broker nunca quebra a requisição.

Logs em JSON com `X-Request-ID` (gerado se ausente e devolvido na resposta).

Detalhes, payloads e deploy em [docs/observability-events.md](docs/observability-events.md).

## Configuração

Variáveis lidas do ambiente ou do `.env` (ver `.env.example`):

| Variável         | Padrão                      | Descrição                                                                   |
| ---------------- | --------------------------- | --------------------------------------------------------------------------- |
| `DATABASE_URL`   | `sqlite:///./onboarding.db` | Compose: `postgresql+psycopg://erp:erp@postgres:5432/erp?options=-csearch_path%3Donboarding` (tabelas no schema `onboarding`) |
| `PORT`           | `8081`                      | Porta usada por `python -m app.main` (8081 é uma das portas abertas na EC2) |
| `AUTH0_DOMAIN`   | —                           | Domínio do tenant, sem `https://` (ex.: `dev-slbrfj6dwk1pdeox.us.auth0.com`) |
| `AUTH0_AUDIENCE` | —                           | Identifier da API no Auth0: `https://erp-banking-api`                       |
| `CORS_ORIGINS`   | `["http://localhost:5173"]` | Origens do frontend, em JSON                                                |
| `RABBITMQ_URL`   | vazio                       | Ex.: `amqp://erp:erp@rabbitmq:5672/`. Vazio = eventos desligados (no-op)     |
| `ROOT_PATH`      | vazio                       | Prefixo do gateway (ex.: `/onboarding`) para o `/docs` funcionar atrás dele |

## Endpoints

| Método | Rota                           | Permissão         | Descrição                                            |
| ------ | ------------------------------ | ----------------- | ---------------------------------------------------- |
| GET    | `/health`                      | pública           | Health check                                         |
| GET    | `/metrics`                     | pública           | Métricas Prometheus (fora do OpenAPI)                |
| GET    | `/customers?q=&limit=&offset=` | `read:customers`  | Lista clientes, com busca por nome ou CPF            |
| POST   | `/customers`                   | `write:customers` | Cria cliente (endereço e perfil financeiro opcionais) |
| GET    | `/customers/{id}`              | `read:customers`  | Consulta cliente (usado pelo Credit Score)           |
| PUT    | `/customers/{id}/anamnesis`    | `write:customers` | Cria/atualiza a anamnese                             |

## Autenticação e autorização (Auth0)

Envie o **access token** do Auth0 em `Authorization: Bearer <token>`. A API valida a
assinatura RS256 via JWKS, o issuer, a audience e a expiração:

- sem token ou com token inválido: **401** (`WWW-Authenticate: Bearer`);
- token válido sem a permissão da rota: **403** (permissões da claim `permissions` do RBAC
  do Auth0, ou de `scope` em tokens machine-to-machine);
- `AUTH0_*` não configurado: **503** (nenhuma rota de negócio fica liberada).

O Credit Score chama `GET /customers/{id}` repassando o token do usuário (token relay), então
quem calcula score também precisa de `read:customers`. Detalhes em [docs/auth.md](docs/auth.md).
