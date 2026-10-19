# Autenticação (Auth0)

O front faz o login (Authorization Code + PKCE) e envia o **access token JWT** em
`Authorization: Bearer <token>`. Esta API **só valida** o token; não existe rota de login aqui.

## O que a API faz

Implementado em `app/core/security.py` (`require_auth`), aplicado em `app/main.py`:

- Baixa o JWKS de `https://<AUTH0_DOMAIN>/.well-known/jwks.json` e valida assinatura RS256.
- Valida `iss` (`https://<AUTH0_DOMAIN>/`, com barra final), `aud`, `exp` e exige `sub`.
- 401 sem token/token inválido (com `WWW-Authenticate: Bearer`); 503 se `AUTH0_*` não estiver configurado.
- `/health` é público. `/docs`, `/redoc` e `/openapi.json` também exigem Bearer.
- CORS liberado para `CORS_ORIGINS` (padrão `http://localhost:5173`) com `Authorization` e `Content-Type`.
- 403 por permissão/role **não** é exigido nesta etapa.

## Variáveis de ambiente (`.env`)

| Variável | Exemplo |
|----------|---------|
| `AUTH0_DOMAIN` | `dev-slbrfj6dwk1pdeox.us.auth0.com` (sem `https://`) |
| `AUTH0_AUDIENCE` | Identifier da API no Auth0 — **igual** ao `VITE_AUTH0_AUDIENCE` do front |
| `CORS_ORIGINS` | `["http://localhost:5173"]` (JSON) |

## ⚠ Pendência: audience

O front está configurado com `VITE_AUTH0_AUDIENCE=https://dev-slbrfj6dwk1pdeox.us.auth0.com/api/v2/`,
que é a **Auth0 Management API**, não a API do ERP. Funciona tecnicamente se o back usar o mesmo
valor, mas o recomendado é:

1. Auth0 → Applications → APIs → Create API, Identifier `https://erp-banking-api`, RS256.
2. Trocar `VITE_AUTH0_AUDIENCE` no front e `AUTH0_AUDIENCE` no back por esse valor.
3. Reiniciar o front (Vite lê `.env` só na inicialização).

No painel, a Application (client `OHeEe32c8zz3iLmp1pnrdfe3wCUElgab`) precisa ter
`http://localhost:5173` em Allowed Callback URLs, Allowed Logout URLs e Allowed Web Origins.

## Decisão pendente: chamadas entre serviços

Score → Onboarding e Transactions → Score ainda não enviam token. Opções: repassar o token do
usuário (simples) ou Machine-to-Machine/client credentials (mais correto). Definir antes de
alterar os clients HTTP e os mocks (`respx`, `MockRestServiceServer`).

## Testes

`tests/test_auth.py` usa chaves RSA geradas localmente e mock do `PyJWKClient`; nenhuma chamada ao Auth0.
Os demais testes sobrescrevem `require_auth` via `dependency_overrides`.
