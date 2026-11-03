# ErpIa - Onboarding API

Serviço do **ErpIa** responsável pelo cadastro de clientes, anamnese financeira e onboarding PJ do
portal do cliente.
Contexto do projeto, arquitetura e autenticação em [docs/](docs/README.md).

## Requisitos

- Python 3.12+ (o CI e a imagem Docker usam 3.13)

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

## Produção (EC2 + API Gateway)

O serviço roda no `docker compose` do repo [erp-banking-infra](https://github.com/GabrielRosa1/erp-banking-infra)
na EC2 `3.235.6.136`, **sem porta publicada**: o acesso público é só pelo API Gateway (nginx) na porta **8080**, com
o prefixo `/onboarding` (removido antes de chegar aqui; por isso `ROOT_PATH=/onboarding`).

| O quê          | URL                                                                   |
| -------------- | --------------------------------------------------------------------- |
| API            | `http://3.235.6.136:8080/onboarding/...` (ex.: `/onboarding/health`)  |
| Swagger        | `http://3.235.6.136:8080/onboarding/docs` (exige Bearer token)        |
| Front (Vercel) | https://erp-banking-front.vercel.app → `/api/onboarding/*` reescrito para o gateway |
| Grafana        | `http://3.235.6.136:8081`                                             |
| Prometheus     | `http://3.235.6.136:8082` (coleta `onboarding-api:8081/metrics` pela rede interna) |

Consumidores dos eventos publicados aqui: `customer.created` → Transactions (fila `transactions.customer-created`,
abre conta corrente com `AUTO_OPEN_ACCOUNT=true`); `customer.anamnesis_updated` → Credit Score (fila
`credit-score.anamnesis-updated`, marca o score como desatualizado).

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

- `GET /metrics`: métricas HTTP padrão (`http_requests_total`, `http_request_duration_seconds`,
  `http_request_duration_highr_seconds`) e de
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
| `PORT`           | `8081`                      | Porta do uvicorn (local e dentro do container)                              |
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
| GET    | `/me`                          | `read:self`       | Customer vinculado ao `sub` do token (portal)        |

### Portal do cliente (Fase 2)

O cliente PJ é identificado pelo `sub` do token (`customers.auth0_sub`, único). `GET /me` responde
`{customer_id, onboarding_status, empresa}`; sem customer: `{customer_id: null, onboarding_status: "NAO_INICIADO", empresa: null}`.
Score e Transactions chamam `GET /me` com o token repassado para descobrir o `customer_id`.

Armazenamento de `empresa`: `razao_social`, `nome_fantasia`, `cnpj`, `email` e `telefone` ficam em `customers`
(`nome` = `razao_social`, `cpf` nulo, `tipo_pessoa = PJ`); `cidade`, `estado`, `fundacao_ano` e `funcionarios`
ficam em `business_profiles`, junto com `segmento`, `respostas`, `observacoes`, `analise` e os dados de revisão.

Migração: `create_all` não altera tabelas existentes, então `app/config/migrations.py` roda no startup e, só em
PostgreSQL, aplica `ADD COLUMN IF NOT EXISTS` das colunas novas, `cpf DROP NOT NULL` e os índices únicos de
`auth0_sub`/`cnpj` (idempotente; no-op em SQLite).

## Autenticação e autorização (Auth0)

Envie o **access token** do Auth0 em `Authorization: Bearer <token>`. A API valida a
assinatura RS256 via JWKS, o issuer, a audience e a expiração:

- sem token ou com token inválido: **401** (`WWW-Authenticate: Bearer`);
- token válido sem a permissão da rota: **403** (permissões da claim `permissions` do RBAC
  do Auth0, ou de `scope` em tokens machine-to-machine);
- `AUTH0_*` não configurado: **503** (nenhuma rota de negócio fica liberada).

O Credit Score chama `GET /customers/{id}` repassando o token do usuário (token relay), então
quem calcula score também precisa de `read:customers`. Detalhes em [docs/auth.md](docs/auth.md).
