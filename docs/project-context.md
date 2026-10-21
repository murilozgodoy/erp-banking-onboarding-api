# Contexto do projeto — ERP Banking e Crédito

Trabalho semestral de Projeto de Software (Insper, prof. Eduardo Santana), grupo de 6.
Plataforma em microsserviços para digitalizar operações bancárias.

## Serviços

| Serviço | Stack | Porta | Função |
|---------|-------|-------|--------|
| Onboarding API (este repo) | Python 3.13 / FastAPI | 8081 | Cadastro de clientes, dados financeiros e anamnese |
| Credit Score API | Python 3.13 / FastAPI | 8082 | Calcula score consultando o Onboarding |
| Transactions API | Java 21 / Spring Boot 3.3 | 8080 | Contas, transações e crédito; consulta o Score |
| Front (erp-banking-front) | React/Vite | 5173 | UI + login Auth0 |

As portas 8080, 8081 e 8082 são as abertas na instância EC2 da AWS.
PostgreSQL único com 3 schemas (um por serviço). Dados de outro serviço só via API, nunca SQL direto.
Dev/testes: SQLite; produção: `DATABASE_URL` (Postgres, driver `psycopg[binary]`).

## Etapas

| Etapa | Entrega | Escopo | Status |
|-------|---------|--------|--------|
| 1 | 09/09/2026 | Arquitetura + repos | Entregue |
| 2 | 28/09/2026 | 3 serviços + testes ≥ 80% | Entregue |
| 3 | 21/10/2026 | Auth0 (OAuth2/JWT + RBAC) + Frontend | Entregue |
| 4 | 04/11/2026 | API Gateway, carga, Prometheus/Grafana, AWS EC2 | Pendente |

## Endpoints desta API

`GET /health` · `GET /customers` · `POST /customers` · `GET /customers/{id}` ·
`PUT /customers/{id}/anamnesis` (todos exceto `/health` exigem Bearer JWT e a permissão da rota).

## Decisões técnicas

- Sem camada repository: o service usa a Session do ORM diretamente; camadas router → service → model (ver [architecture.md](architecture.md)).
- Testes: pytest + cobertura mínima 80% (atual ~98%), CI no GitHub Actions + build Docker.
- Auth: JWT do Auth0 + RBAC por permissões; chamadas entre serviços repassam o token do usuário (ver [auth.md](auth.md)).

## Histórico recente

- 2026-10-19: refatoração para estrutura FastAPI em camadas (`config`, `core`, `models`, `schemas`,
  `services`, `routers`; sem `repositories`, o service usa a Session do ORM); criação de `docs/`; revisão da configuração de login.
- 2026-10-21: autorização por permissões (RBAC) com 403 por rota; listagem e busca de clientes
  (`GET /customers`); portas padronizadas com a EC2 (Onboarding 8081, Score 8082, Transactions 8080).
