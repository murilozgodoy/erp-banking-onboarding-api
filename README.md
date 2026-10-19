# ERP Banking - Onboarding API

Serviço responsável pelo cadastro de clientes e anamnese financeira.

## Requisitos

- Python 3.11+

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows PowerShell
pip install -r requirements-dev.txt
```

## Executar

```bash
uvicorn app.main:app --reload --port 8001
```

Docs interativas: http://localhost:8001/docs

## Testes com cobertura

```bash
pytest
```

Cobertura mínima exigida: **80%** (falha o build se abaixo).

## Configuração

Variáveis (ver `.env.example`):
- `DATABASE_URL` — padrão `sqlite:///./onboarding.db`. Pode ser trocado por Postgres (ex: `postgresql+psycopg2://user:pass@host:5432/db`).

## Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/health` | Health check |
| POST | `/customers` | Cria cliente (opcional endereço + perfil financeiro) |
| GET | `/customers/{id}` | Consulta dados autorizados |
| PUT | `/customers/{id}/anamnesis` | Cria/atualiza anamnese |

## Autenticação Auth0 (Etapa 3)

Envie o **access token** em `Authorization: Bearer <token>`.
A API valida assinatura RS256 via JWKS, issuer HTTPS com barra final,
audience e expiração. `/health` permanece público; preflight CORS não exige token.
Sem token ou com token inválido: **401**, com `WWW-Authenticate: Bearer`.
Roles/permissões por rota ainda não são exigidas; não há uma regra de 403 por escopo nesta etapa.

Configure `AUTH0_DOMAIN` (somente hostname, sem https:// nem barra final) e
`AUTH0_AUDIENCE` (Identifier da API no Auth0). O valor `https://erp-banking-api`
no exemplo precisa ser confirmado no painel e deve coincidir com `VITE_AUTH0_AUDIENCE`.
Não use ID token ou token opaco. Nenhuma credencial de client secret é necessária para validar JWT.

CORS permite `http://localhost:5173`, os métodos utilizados e os headers
`Authorization` e `Content-Type`. Configure `CORS_ORIGINS` para produção.

Os testes usam chaves RSA e tokens locais ou autenticação simulada, sem chamadas ao Auth0.

**Pendente de decisão:** as chamadas Score → Onboarding e Transactions → Score
precisam de propagação do token do usuário ou Machine-to-Machine. Os clients atuais
ainda não enviam credenciais: esses fluxos entre serviços retornarão erro até a escolha ser implementada.

Python carrega `.env` automaticamente. `CORS_ORIGINS` usa JSON, por exemplo
`["http://localhost:5173","https://app.example.com"]`. Sem configuração Auth0,
requisições com Bearer recebem 503; nenhuma rota de negócio é liberada.
`/docs`, `/redoc` e `/openapi.json` também exigem Bearer (abra com um cliente que envie o header).
