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
| GET    | `/me/onboarding`               | `read:self`       | Rascunho ou envio atual do onboarding PJ             |
| PUT    | `/me/onboarding`               | `write:self`      | Salva rascunho (`enviar=false`) ou envia (`enviar=true`) |

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

**Onboarding PJ (`/me/onboarding`).** `GET` responde `{empresa, segmento, respostas, observacoes,
onboarding_status, updated_at}` (sem customer: `empresa: null`, `respostas: {}`, `NAO_INICIADO`). `PUT` recebe
`{empresa, segmento, respostas, observacoes, enviar}`, cria ou atualiza o customer PJ do `sub` (o corpo
**substitui** o estado salvo) e responde no mesmo formato do `GET`.

- `empresa` é validada sempre (inclusive no rascunho), com 422 no formato padrão do FastAPI: `cnpj` com
  14 dígitos e DV válido (aceita máscara, guardado só com dígitos), `estado` = UF válida (maiúscula), `email`,
  `telefone` (8 a 20), `fundacao_ano` (até o ano atual), `funcionarios` ≥ 0. `segmento` deve ser um dos templates.
- `enviar=false` → `RASCUNHO` (dados parciais aceitos).
- `enviar=true` exige `empresa.razao_social|cnpj|email|telefone|cidade|estado`, `segmento` e as respostas
  válidas no template (`app.templates.validate_respostas`). Falha → **422**
  `{"detail": "Onboarding incompleto ou inválido", "campos": [{"campo": "empresa.cnpj"|"segmento"|"<id do campo>", "erro": "..."}]}`
  e nada é salvo. Sucesso → `EM_ANALISE`, `submitted_at`, publica `customer.onboarding_submitted`
  (`customer_id, auth0_sub, segmento, empresa, respostas, observacoes` + envelope).
- Editar/reenviar só a partir de `RASCUNHO` ou `REPROVADO` (no reenvio, a análise e a revisão anteriores são
  limpas); em `EM_ANALISE`, `ANALISE_MANUAL` ou `APROVADO` → **409**. CNPJ de outro customer → **409**.
- **Decisão:** o cadastro PJ **não** publica `customer.created`; o seeder do Transactions abre a conta PJ a partir
  de `customer.onboarding_submitted`.
- Métricas: `onboarding_submissions_total{segmento}` (séries zeradas para os 9 segmentos) e
  `onboarding_drafts_saved_total`.

## Templates de onboarding por segmento

`GET /onboarding/templates` (qualquer usuário autenticado) devolve os templates do onboarding de empresas, e
`GET /onboarding/templates/{segmento}` devolve um só (404 se não existir). São dados versionados no código, em
`app/templates/data.py`, no formato `{segmento, versao, nome, descricao, icone, secoes: [{id, titulo, campos:
[{id, label, tipo, obrigatorio, opcoes?, ajuda?, min?, max?}]}]}`. Segmentos: `varejo`, `alimentacao`,
`servicos`, `saude`, `tecnologia`, `industria`, `agro`, `construcao` e `outro`.

- Todo template tem 3 seções (`vendas`, `operacao`, `financeiro`) e de 8 a 14 campos. Os campos comuns têm o
  mesmo id em todos os segmentos (`faturamento_mensal`, `margem_bruta_pct`, `sazonalidade`,
  `prazo_medio_recebimento_dias`, `prazo_medio_pagamento_dias`, `folha_mensal`, `possui_estoque`,
  `valor_estoque`, `dividas_total`, `parcela_dividas_mensal`), porque o Credit Score e o Transactions leem
  essas chaves. `ticket_medio` e `pct_cartao_credito` também mantêm o id onde aparecem.
- `validate_respostas(segmento, respostas)` devolve `[{"campo", "erro"}]` (vazio quando válido): obrigatórios,
  tipos (`currency|number` ≥ 0, `percent` de 0 a 100, `integer`, `boolean`, `select`, `multiselect`, `text` com
  até `max` caracteres, padrão 1000), `min`/`max` e `valor_estoque` obrigatório quando `possui_estoque` é
  verdadeiro. Chaves desconhecidas são ignoradas.

**Novo segmento:** adicione um `_template(...)` em `TEMPLATES` (`app/templates/data.py`) com os campos
específicos em `vendas`/`operacao`, use um ícone do [lucide](https://lucide.dev/icons), atualize `VERSAO` e
rode os testes (`tests/test_templates.py` verifica a estrutura de todos os segmentos). Avise o Score e o front.

## Autenticação e autorização (Auth0)

Envie o **access token** do Auth0 em `Authorization: Bearer <token>`. A API valida a
assinatura RS256 via JWKS, o issuer, a audience e a expiração:

- sem token ou com token inválido: **401** (`WWW-Authenticate: Bearer`);
- token válido sem a permissão da rota: **403** (permissões da claim `permissions` do RBAC
  do Auth0, ou de `scope` em tokens machine-to-machine);
- `AUTH0_*` não configurado: **503** (nenhuma rota de negócio fica liberada).

O Credit Score chama `GET /customers/{id}` repassando o token do usuário (token relay), então
quem calcula score também precisa de `read:customers`. Detalhes em [docs/auth.md](docs/auth.md).
