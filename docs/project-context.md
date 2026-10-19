# Contexto do projeto — ERP Banking e Crédito

Trabalho semestral de Projeto de Software (Insper, prof. Eduardo Santana), grupo de 6.
Plataforma em microsserviços para digitalizar operações bancárias.

## Serviços

| Serviço | Stack | Porta | Função |
|---------|-------|-------|--------|
| Onboarding API (este repo) | Python 3.13 / FastAPI | 8081 | Cadastro de clientes, dados financeiros e anamnese |
| Credit Score API | Python 3.13 / FastAPI | 8002 | Calcula score consultando o Onboarding |
| Transactions API | Java 21 / Spring Boot 3.3 | 8080 | Contas, transações e crédito; consulta o Score |
| Front (erp-banking-front) | React/Vite | 5173 | UI + login Auth0 |

PostgreSQL único com 3 schemas (um por serviço). Dados de outro serviço só via API, nunca SQL direto.
Dev/testes: SQLite; produção: `DATABASE_URL` (Postgres, driver `psycopg[binary]`).

## Etapas

| Etapa | Entrega | Escopo | Status |
|-------|---------|--------|--------|
| 1 | 09/09/2026 | Arquitetura + repos | Entregue |
| 2 | 28/09/2026 | 3 serviços + testes ≥ 80% | Entregue |
| 3 | 21/10/2026 | Auth0 (OAuth2/JWT) + Frontend | Em andamento |
| 4 | 04/11/2026 | API Gateway, carga, Prometheus/Grafana, AWS EC2 | Pendente |

## Endpoints desta API

`GET /health` · `POST /customers` · `GET /customers/{id}` · `PUT /customers/{id}/anamnesis`
(todos exceto `/health` exigem Bearer JWT).

## Decisões técnicas

- Sem camada repository: o service usa a Session do ORM diretamente; camadas router → service → model (ver [architecture.md](architecture.md)).
- Testes: pytest + cobertura mínima 80% (atual ~97%), CI no GitHub Actions + build Docker.
- Auth: ver [auth.md](auth.md).

## Histórico recente

- 2026-10-19: refatoração para estrutura FastAPI em camadas (`config`, `core`, `models`, `schemas`,
  `services`, `routers`; sem `repositories`, o service usa a Session do ORM); criação de `docs/`; revisão da configuração de login.
