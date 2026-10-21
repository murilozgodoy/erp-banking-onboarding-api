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

Cobertura mínima exigida: **80%** (falha o build se abaixo).

## Configuração

Variáveis lidas do ambiente ou do `.env` (ver `.env.example`):

| Variável         | Padrão                      | Descrição                                                                   |
| ---------------- | --------------------------- | --------------------------------------------------------------------------- |
| `DATABASE_URL`   | `sqlite:///./onboarding.db` | Em produção, PostgreSQL: `postgresql+psycopg://user:pass@host:5432/db`      |
| `PORT`           | `8081`                      | Porta usada por `python -m app.main` (8081 é uma das portas abertas na EC2) |
| `AUTH0_DOMAIN`   | —                           | Domínio do tenant, sem `https://` (ex.: `dev-slbrfj6dwk1pdeox.us.auth0.com`) |
| `AUTH0_AUDIENCE` | —                           | Identifier da API no Auth0: `https://erp-banking-api`                       |
| `CORS_ORIGINS`   | `["http://localhost:5173"]` | Origens do frontend, em JSON                                                |

## Endpoints

| Método | Rota                           | Permissão         | Descrição                                            |
| ------ | ------------------------------ | ----------------- | ---------------------------------------------------- |
| GET    | `/health`                      | pública           | Health check                                         |
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
