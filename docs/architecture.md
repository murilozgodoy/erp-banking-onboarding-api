# Arquitetura da Onboarding API

```
app/
├── main.py              # create_app(): CORS, routers, proteção por JWT
├── config/
│   ├── settings.py      # Settings (pydantic-settings, lê .env)
│   └── database.py      # engine, SessionLocal, Base, get_db
├── core/
│   └── security.py      # require_auth (JWT Auth0, JWKS/RS256) e require_permission (RBAC, 403)
├── models/              # entidades SQLAlchemy (um arquivo por tabela)
├── schemas/             # DTOs Pydantic de entrada/saída
├── services/            # regras de negócio e acesso a dados via Session do ORM; exceções de domínio
└── routers/             # endpoints HTTP (traduzem exceções de domínio em HTTP)
tests/                   # pytest (cobertura mínima 80%)
docs/                    # contexto atualizado do projeto
```

## Fluxo de uma requisição

`router` → `service` (regra de negócio + Session do SQLAlchemy) → `model`.
Os `schemas` validam a entrada e serializam a saída no router.

## Convenções

- Imports sempre absolutos a partir de `app.` (ex.: `from app.config.settings import settings`).
- Novas tabelas: criar o arquivo em `app/models/` e exportar em `app/models/__init__.py`
  (necessário para `Base.metadata.create_all` enxergá-las).
- Exceções de domínio ficam no service; o router converte para `HTTPException`.
- Rotas declaram a permissão exigida com `Depends(require_permission("read:customers"))`.
- Testes substituem dependências com `app.dependency_overrides` (`get_db`, `require_auth`).

## Tabelas (schema onboarding)

`customers`, `addresses`, `financial_profiles`, `anamnesis` — ver `app/models/`.
