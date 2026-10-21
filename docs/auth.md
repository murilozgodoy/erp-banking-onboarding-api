# Autenticação e autorização (Auth0)

O front faz o login (Authorization Code + PKCE) e envia o **access token JWT** em
`Authorization: Bearer <token>`. Esta API **só valida** o token; não existe rota de login aqui.
O passo a passo do painel do Auth0 (API, permissões e perfis) está em
[erp-banking-front/docs/auth0.md](https://github.com/murilozgodoy/erp-banking-front/blob/main/docs/auth0.md).

## O que a API faz

Implementado em `app/core/security.py`:

- `require_auth` baixa o JWKS de `https://<AUTH0_DOMAIN>/.well-known/jwks.json` e valida assinatura
  RS256, `iss` (`https://<AUTH0_DOMAIN>/`, com barra final), `aud`, `exp` e exige `sub`.
  Devolve um `Principal` (token, `sub` e permissões).
- `require_permission("<permissão>")` responde **403** quando a permissão não está no token.
  As permissões vêm da claim `permissions` (RBAC do Auth0) e também de `scope`.
- 401 sem token ou com token inválido (com `WWW-Authenticate: Bearer`); 503 se `AUTH0_*` não estiver configurado.
- `/health` é público. `/docs`, `/redoc` e `/openapi.json` exigem um token válido (qualquer permissão).
- CORS liberado para `CORS_ORIGINS` (padrão `http://localhost:5173`) com `Authorization` e `Content-Type`.

## Permissões das rotas

| Rota                                                  | Permissão         |
| ----------------------------------------------------- | ----------------- |
| `GET /customers`, `GET /customers/{id}`               | `read:customers`  |
| `POST /customers`, `PUT /customers/{id}/anamnesis`    | `write:customers` |

## Chamadas entre serviços: token relay

O Credit Score chama `GET /customers/{id}` repassando o mesmo access token que recebeu do front.
Esta API valida esse token como qualquer outro, então a permissão `read:customers` do usuário é
verificada aqui também (o perfil `atendente` não calcula score; `analista` e `admin` têm as duas
permissões).

## Variáveis de ambiente (`.env`)

| Variável         | Exemplo                                              |
| ---------------- | ---------------------------------------------------- |
| `AUTH0_DOMAIN`   | `dev-slbrfj6dwk1pdeox.us.auth0.com` (sem `https://`) |
| `AUTH0_AUDIENCE` | `https://erp-banking-api` (igual ao `VITE_AUTH0_AUDIENCE` do front) |
| `CORS_ORIGINS`   | `["http://localhost:5173"]` (JSON)                   |

## Testes

`tests/test_auth.py` usa chaves RSA geradas localmente e mock do `PyJWKClient` (nenhuma chamada ao
Auth0): cobre assinatura, claims, 401, 403 por permissão, permissões via `scope` e CORS.
Os demais testes sobrescrevem `require_auth` via `dependency_overrides` com um `Principal` que
tem todas as permissões.
