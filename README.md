# ErpIa - Onboarding API

Serviço do **ErpIa** responsável pelo cadastro de clientes PF do backoffice (com anamnese financeira), pelo
**onboarding PJ** do portal do cliente, pela **fila de análise manual** e pela **equipe da empresa** (membros,
convites e permissões). Contexto do projeto, arquitetura e autenticação em [docs/](docs/README.md); a visão de
ponta a ponta da Fase 2 está em `docs/portal-cliente.md` e `docs/apis-fase-2.md` do repositório do front.

## Sumário

- [Executar localmente](#executar-localmente)
- [Configuração](#configuração)
- [Endpoints](#endpoints)
- [Portal do cliente: `/me` e onboarding PJ](#portal-do-cliente-me-e-onboarding-pj)
- [Templates por segmento](#templates-por-segmento)
- [Análise manual](#análise-manual)
- [Equipe e permissões](#equipe-e-permissões)
- [Eventos e outbox](#eventos-e-outbox)
- [Métricas e logs](#métricas-e-logs)
- [Autenticação e autorização (Auth0)](#autenticação-e-autorização-auth0)
- [Produção (EC2 + API Gateway)](#produção-ec2--api-gateway)

## Executar localmente

Requisitos: Python 3.12+ (o CI e a imagem Docker usam 3.13).

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows PowerShell
pip install -r requirements-dev.txt
cp .env.example .env
python -m app.main          # http://localhost:8081 (porta em PORT)
pytest                      # testes com cobertura mínima de 80% (o RabbitMQ é mockado)
```

Docs interativas em `http://localhost:8081/docs` (exigem Bearer token).

**Docker:** `docker build -t onboarding-api .` e `docker run --rm -p 8081:8081 --env-file .env onboarding-api`.
Imagem `python:3.13-slim`, usuário não-root, `HEALTHCHECK` em `/health` e porta via `PORT`. Em push na `main` o CI
publica `ghcr.io/murilozgodoy/erp-banking-onboarding-api:latest` e `:<sha>`.

**Banco e migração:** no startup roda `create_all` e `app/config/migrations.py`, que no PostgreSQL aplica de forma
idempotente as colunas e índices novos (`ADD COLUMN IF NOT EXISTS`, índices únicos de `auth0_sub` e `cnpj`) e cria
o DONO de toda empresa PJ que ainda não tem um (no-op em SQLite).

## Configuração

Variáveis lidas do ambiente ou do `.env` (`app/config/settings.py` e `app/config/database.py`; ver `.env.example`).
Nunca commite credenciais: use os placeholders abaixo.

| Variável              | Padrão                      | Descrição                                                                                       |
| --------------------- | --------------------------- | ----------------------------------------------------------------------------------------------- |
| `DATABASE_URL`        | `sqlite:///./onboarding.db` | URL do SQLAlchemy. As tabelas ficam no schema do `search_path` (exemplos abaixo)                |
| `DB_POOL_SIZE`        | `5`                         | Conexões fixas do pool (só PostgreSQL). Na Aiven free usamos `2`                                |
| `DB_MAX_OVERFLOW`     | `5`                         | Conexões extras além do pool. Na Aiven free usamos `1`                                          |
| `DB_POOL_RECYCLE`     | `1800`                      | Segundos até reciclar uma conexão (abaixo do idle timeout do provedor); há também `pool_pre_ping` |
| `RABBITMQ_URL`        | vazio                       | Ex.: `amqp://<USUARIO>:<SENHA>@rabbitmq:5672/`. Vazio desliga publisher, consumer e relay       |
| `OUTBOX_POLL_SECONDS` | `10`                        | Intervalo do relay do outbox; `<= 0` desliga o relay                                            |
| `FRONT_URL`           | vazio                       | Base do link de convite; vazio = `https://erp-banking-front.vercel.app`                         |
| `ROOT_PATH`           | vazio                       | Prefixo do gateway (ex.: `/onboarding`). **Só** afeta o OpenAPI e o Swagger (`servers` e `openapi.json`); não entra no roteamento |
| `AUTH0_DOMAIN`        | vazio                       | Domínio do tenant, sem `https://` (ex.: `<TENANT>.us.auth0.com`)                                |
| `AUTH0_AUDIENCE`      | vazio                       | Identifier da API no Auth0: `https://erp-banking-api`                                           |
| `CORS_ORIGINS`        | `["http://localhost:5173"]` | Origens do front, em JSON                                                                       |
| `PORT`                | `8081`                      | Porta do uvicorn                                                                                |
| `LOG_LEVEL`           | `INFO`                      | Nível dos logs JSON                                                                             |
| `APP_NAME`            | `erp-banking-onboarding-api` | Nome do serviço nos logs                                                                       |

Exemplos de `DATABASE_URL`:

```bash
# Postgres do compose (schema onboarding)
DATABASE_URL=postgresql+psycopg://erp:erp@postgres:5432/erp?options=-csearch_path%3Donboarding
# Postgres gerenciado na Aiven (SSL obrigatório; poucas conexões, então pool pequeno)
DATABASE_URL=postgresql+psycopg://<USUARIO>:<SENHA>@<HOST>.aivencloud.com:<PORTA>/defaultdb?sslmode=require&options=-csearch_path%3Donboarding
DB_POOL_SIZE=2
DB_MAX_OVERFLOW=1
```

**Decisão sobre `ROOT_PATH`:** ele não é passado ao `FastAPI(root_path=...)`, porque o Starlette remove o
`root_path` do início do caminho e as rotas `/onboarding/templates` e `/onboarding/reviews` começam com o mesmo
texto do prefixo `/onboarding` (davam 404 dentro do container).

## Endpoints

| Método | Rota                                         | Permissão do token  | Descrição                                                 |
| ------ | -------------------------------------------- | ------------------- | --------------------------------------------------------- |
| GET    | `/health`                                    | pública             | Health check                                              |
| GET    | `/metrics`                                   | pública             | Métricas Prometheus (fora do OpenAPI)                     |
| GET    | `/docs`, `/redoc`, `/openapi.json`           | autenticado         | Documentação interativa                                   |
| GET    | `/customers?q=&limit=&offset=`               | `read:customers`    | Clientes PF, com busca por nome ou CPF                    |
| POST   | `/customers`                                 | `write:customers`   | Cria cliente PF (endereço e perfil financeiro opcionais)  |
| GET    | `/customers/{id}`                            | `read:customers`    | Consulta cliente (usado pelo Credit Score)                |
| PUT    | `/customers/{id}/anamnesis`                  | `write:customers`   | Cria ou atualiza a anamnese                               |
| GET    | `/onboarding/templates`                      | autenticado         | Templates de todos os segmentos                           |
| GET    | `/onboarding/templates/{segmento}`           | autenticado         | Um template (404 se o segmento não existir)               |
| GET    | `/me`                                        | `read:self`         | Empresa e `membro` do `sub` do token                      |
| GET    | `/me/onboarding`                             | `read:self`         | Rascunho ou envio atual (qualquer membro ATIVO)           |
| PUT    | `/me/onboarding`                             | `write:self`        | Salva rascunho ou envia (só o DONO)                       |
| GET    | `/onboarding/reviews?status=`                | `review:onboarding` | Fila de análise (padrão `ANALISE_MANUAL`)                 |
| POST   | `/onboarding/reviews/{customer_id}/decision` | `review:onboarding` | `{decisao: APROVADO\|REPROVADO, comentario}`              |
| GET    | `/me/team`                                   | `read:self`         | Membros da empresa (exige `gerenciar_equipe`)             |
| POST   | `/me/team/invites`                           | `write:self`        | Convida uma pessoa (exige `gerenciar_equipe`)             |
| PATCH  | `/me/team/{id}`                              | `write:self`        | Edita papel, permissões, limite ou status (idem)          |
| DELETE | `/me/team/{id}`                              | `write:self`        | Revoga o convite ou remove o membro (idem)                |
| POST   | `/me/team/invites/{token}/accept`            | `read:self`         | Aceita o convite                                          |

Erros de negócio usam o corpo `{"error": "<CODIGO>", ...}`; erros de validação do FastAPI saem em 422 no formato
padrão.

## Portal do cliente: `/me` e onboarding PJ

O cliente PJ é identificado pelo `sub` do token: `customers.auth0_sub` (único) para o dono ou
`company_members.auth0_sub` para um funcionário. Score e Transactions chamam `GET /me` com o token repassado para
descobrir o `customer_id` e as permissões.

**`GET /me`** → `{customer_id, onboarding_status, empresa, membro}`:

```json
{
  "customer_id": 12,
  "onboarding_status": "APROVADO",
  "empresa": { "razao_social": "Aurora Pães Ltda", "cnpj": "11222333000181", "...": "..." },
  "membro": {
    "id": 3,
    "nome": "Fulano",
    "email": "fulano@empresa.com",
    "papel": "OPERADOR",
    "permissoes": ["ver_financeiro", "pagar", "gerenciar_estoque", "usar_assistente"],
    "limite_pagamento": 1500.0,
    "status": "ATIVO"
  }
}
```

Sem empresa: `{customer_id: null, onboarding_status: "NAO_INICIADO", empresa: null, membro: null}`. Membro
suspenso → 403 `{"error":"MEMBRO_SUSPENSO"}`. `membro.nome` e `membro.email` são extras ao contrato (auditoria
`created_by_nome` do Transactions).

`empresa` = `{razao_social, nome_fantasia, cnpj, email, telefone, cidade, estado, fundacao_ano, funcionarios}`.
Identificação e contato ficam em `customers` (`nome` = `razao_social`, `cpf` nulo, `tipo_pessoa = PJ`); `cidade`,
`estado`, `fundacao_ano` e `funcionarios` ficam em `business_profiles`, com `segmento`, `respostas`,
`observacoes`, `analise`, `submission_event_id` e os dados da revisão.

**`GET /me/onboarding`** → `{empresa, segmento, respostas, observacoes, onboarding_status, updated_at,
review_comment, reviewed_at}` (os dois últimos só depois de uma decisão manual). **`PUT /me/onboarding`** recebe
`{empresa, segmento, respostas, observacoes, enviar}`, cria ou atualiza a empresa do `sub` (o corpo **substitui** o
estado salvo) e responde no mesmo formato.

- `empresa` é validada sempre, inclusive no rascunho: `cnpj` com 14 dígitos e DV válido (aceita máscara, guardado só
  com dígitos), `estado` = UF válida, `email`, `telefone` (8 a 20), `fundacao_ano` (até o ano atual) e
  `funcionarios` ≥ 0. `segmento` deve ser um dos templates.
- `enviar=false` → `RASCUNHO` (dados parciais aceitos).
- `enviar=true` exige `razao_social`, `cnpj`, `email`, `telefone`, `cidade`, `estado`, o `segmento` e as respostas
  válidas no template. Falha → **422**
  `{"detail": "Onboarding incompleto ou inválido", "campos": [{"campo": "empresa.cnpj", "erro": "Campo obrigatório."}]}`
  e nada é salvo. Sucesso → `EM_ANALISE`, `submitted_at`, novo `submission_event_id` e o evento
  `customer.onboarding_submitted` no outbox, na mesma transação.
- **Decisões:** só o DONO altera o onboarding (quem ainda não tem empresa vira o DONO); outro membro → 403
  `{"error":"SEM_PERMISSAO","permissao":"dono"}`. Editar ou reenviar só a partir de `RASCUNHO` ou `REPROVADO` (no
  reenvio, a análise e a revisão anteriores são limpas); em outro status → 409. CNPJ de outra empresa → 409. O
  status muda por compare-and-set, então dois envios simultâneos não passam os dois. O cadastro PJ **não** publica
  `customer.created`: o Transactions abre a conta PJ a partir de `customer.onboarding_submitted`.

**Status** (`customers.onboarding_status`): `NAO_INICIADO` (só na resposta) → `RASCUNHO` → `EM_ANALISE` →
`APROVADO` | `ANALISE_MANUAL` → (analista) `APROVADO` | `REPROVADO`. Clientes PF do backoffice ficam com status nulo.

## Templates por segmento

`GET /onboarding/templates` devolve os templates, dados versionados em `app/templates/data.py`, no formato
`{segmento, versao, nome, descricao, icone, secoes: [{id, titulo, campos: [{id, label, tipo, obrigatorio, opcoes?,
ajuda?, min?, max?}]}]}`. Segmentos: `varejo`, `alimentacao`, `servicos`, `saude`, `tecnologia`, `industria`,
`agro`, `construcao` e `outro` (só campos genéricos e sempre vai para a análise manual).

- Todo template tem 3 seções (`vendas`, `operacao`, `financeiro`) e de 8 a 14 campos. Os campos comuns têm o mesmo
  id em todos os segmentos, porque o Score e o Transactions leem essas chaves: `faturamento_mensal`,
  `margem_bruta_pct`, `sazonalidade`, `prazo_medio_recebimento_dias`, `prazo_medio_pagamento_dias`, `folha_mensal`,
  `possui_estoque`, `valor_estoque`, `dividas_total`, `parcela_dividas_mensal` (e `ticket_medio`,
  `pct_cartao_credito` onde aparecem).
- Tipos: `currency|number` (≥ 0), `percent` (0 a 100), `integer`, `boolean`, `select`, `multiselect` e `text` (até
  `max` caracteres, padrão 1000), com `min`/`max` quando houver. `valor_estoque` é obrigatório quando
  `possui_estoque` é verdadeiro. Chaves desconhecidas são ignoradas.
- **Novo segmento:** adicione um `_template(...)` em `TEMPLATES`, use um ícone do [lucide](https://lucide.dev/icons),
  atualize `VERSAO`, rode `tests/test_templates.py` e avise o Score e o front.

## Análise manual

`GET /onboarding/reviews?status=ANALISE_MANUAL` (aceita qualquer status persistido) devolve
`[{customer_id, empresa, segmento, observacoes, analise, submitted_at}]` em ordem de envio. `analise` é o **resumo**
do evento do Score (`{score, faixa_risco, gerado_por, status}`); o Onboarding não chama o Score de forma síncrona,
e o front busca a análise completa em Score `GET /scores/analyses/{customer_id}`.

`POST /onboarding/reviews/{customer_id}/decision` com `{decisao: "APROVADO"|"REPROVADO", comentario}` (até 2.000
caracteres) só vale a partir de `ANALISE_MANUAL` (compare-and-set: com dois analistas ao mesmo tempo, o segundo
recebe 409; 404 sem onboarding). Grava `reviewed_by` (= `sub` do analista), comentário e data, põe
`customer.onboarding_reviewed` no outbox na mesma transação e responde
`{customer_id, onboarding_status, decisao, comentario, reviewer, reviewed_at}`.

## Equipe e permissões

Tabela `company_members`: `id`, `customer_id`, `auth0_sub` (nulo até aceitar), `email` (minúsculas), `nome`,
`papel` (`DONO|ADMIN|FINANCEIRO|OPERADOR|LEITURA`), `permissoes` (JSON), `limite_pagamento` (nulo = sem limite),
`status` (`CONVIDADO|ATIVO|SUSPENSO`), `invite_token_hash`, `invite_expires_at`, `created_by`, `created_at`,
`updated_at`. Índices únicos em `auth0_sub` e `invite_token_hash`, único parcial `customer_id WHERE papel = 'DONO'`
(**exatamente um DONO por empresa**) e único parcial `(customer_id, email)` para convites e membros ativos.

- **Permissões** (`app/team/permissions.py`): `ver_financeiro`, `pagar`, `aprovar_pagamentos`, `pedir_credito`,
  `contratar_credito`, `gerenciar_estoque`, `gerenciar_equipe`, `usar_assistente`. Presets: DONO e ADMIN = todas;
  FINANCEIRO = ver_financeiro, pagar, aprovar_pagamentos, pedir_credito, usar_assistente; OPERADOR = ver_financeiro,
  pagar, gerenciar_estoque, usar_assistente; LEITURA = ver_financeiro. O DONO tem sempre todas.
- **Quem é o DONO:** `customers.auth0_sub` é a fonte da verdade da posse. Quem cria a empresa vira DONO na mesma
  transação; no startup, um `INSERT ... SELECT ... WHERE NOT EXISTS ... ON CONFLICT DO NOTHING` cria o DONO das
  empresas PJ que não têm (idempotente e seguro com réplicas). O resolver (`app/team/resolver.py`) sincroniza o
  `auth0_sub` do DONO com o do customer.
- **Convite:** `{email, nome, papel, permissoes?, limite_pagamento?}` com `papel` em `ADMIN|FINANCEIRO|OPERADOR|LEITURA`
  (sem `permissoes`, usa o preset) → 201 `{membro, convite_url}`. O token é `secrets.token_urlsafe(32)`, guardado
  **só como sha256**, válido por 7 dias, e aparece apenas nessa resposta, em `{FRONT_URL}/convite/<token>`. Sem
  e-mail na v1.
- **Aceite:** só `read:self`. Grava o `sub`, muda para ATIVO e limpa o hash. Idempotente para o mesmo `sub`.
- **PATCH:** trocar o `papel` sem mandar `permissoes` aplica o preset; `limite_pagamento: null` remove o limite.
- **Regras de proteção:** o DONO não é editável, suspenso nem removido; ninguém vira DONO na v1; ninguém edita ou
  remove a si mesmo; quem não é DONO só concede permissões que tem, só define `limite_pagamento` até o próprio
  (`null`, sem limite, só se o dele também for `null`) e só convida, atribui, edita, suspende, reativa ou remove
  papéis abaixo do seu (DONO > ADMIN > FINANCEIRO > OPERADOR > LEITURA; ADMIN não gerencia ADMIN). O 404 de id
  de outra empresa vem antes desses 403. Todo UPDATE/DELETE leva `customer_id` e
  `papel <> 'DONO'` no WHERE, e o PATCH compara o `updated_at` lido (otimista).

| Status | `error`                  | Quando                                                            |
| ------ | ------------------------ | ----------------------------------------------------------------- |
| 403    | `SEM_PERMISSAO`          | Sem `gerenciar_equipe`, ou concedendo permissão que não tem       |
| 403    | `SEM_PERMISSAO` + `"permissao":"limite_pagamento"` | Não-DONO definindo limite acima do próprio, ou `null` tendo limite |
| 403    | `SEM_PERMISSAO` + `"permissao":"hierarquia"` | Não-DONO agindo sobre ou atribuindo papel igual/acima do seu |
| 403    | `DONO_PROTEGIDO`         | Editar, suspender ou remover o DONO                               |
| 403    | `AUTO_EDICAO`            | Editar ou remover a si mesmo                                      |
| 404    | `MEMBRO_NAO_ENCONTRADO`  | Id inexistente ou de outra empresa                                |
| 409    | `DONO_UNICO`             | O DONO tentando promover alguém a DONO (sem transferência na v1)  |
| 409    | `EMAIL_JA_CADASTRADO`    | E-mail já existe na empresa (suspenso: reative com PATCH)         |
| 409    | `CONVITE_PENDENTE`       | Mudar o status de um convite não aceito (revogue com DELETE)      |
| 409    | `CONFLITO_CONCORRENTE`   | Edição simultânea do mesmo membro                                 |
| 404    | `CONVITE_NAO_ENCONTRADO` | Aceite com token desconhecido                                     |
| 410    | `CONVITE_EXPIRADO`       | Aceite depois de 7 dias                                           |
| 409    | `JA_VINCULADO`           | O `sub` já é dono ou membro de outra empresa                      |

## Eventos e outbox

Exchange `erp.events` (topic, durável), envelope `event_id`, `event_type`, `occurred_at`, mensagens persistentes.

| Routing key                     | Direção                                        | Payload                                                                       |
| ------------------------------- | ---------------------------------------------- | ----------------------------------------------------------------------------- |
| `customer.created`              | publica (após `POST /customers`)               | `customer_id, nome, cpf, email`                                               |
| `customer.anamnesis_updated`    | publica (após a anamnese)                      | `customer_id, dividas_ativas, comprometimento_renda`                          |
| `customer.onboarding_submitted` | publica (envio do onboarding, outbox)          | `customer_id, auth0_sub, segmento, empresa, respostas, observacoes`           |
| `customer.onboarding_reviewed`  | publica (decisão do analista, outbox)          | `customer_id, decisao, comentario, reviewer`                                  |
| `company.member_changed`        | publica (mudança na equipe, outbox)            | `customer_id, member_id, acao, papel, permissoes`                             |
| `business.analysis_completed`   | consome na fila `onboarding.analysis-completed` | `customer_id, status, score, faixa_risco, gerado_por, source_event_id`       |

- Consumidores dos eventos publicados: `customer.created` → Transactions; `customer.anamnesis_updated`,
  `customer.onboarding_reviewed` → Score; `customer.onboarding_submitted` → Score e Transactions.
  `company.member_changed` (`acao` = `CONVIDADO|ATUALIZADO|SUSPENSO|REATIVADO|REMOVIDO|ACEITO`) é só auditoria.
- **Outbox transacional** (`outbox_events`: `event_id` único, `routing_key`, `payload`, `created_at`,
  `published_at`, `attempts`, `last_error`): os três eventos marcados acima são gravados **na mesma transação** da
  mudança de estado. Depois do commit são publicados na hora (BackgroundTasks); se o broker estava fora ou o
  processo caiu, o relay do lifespan republica a cada `OUTBOX_POLL_SECONDS` as linhas pendentes com mais de 5 s,
  em lotes de 50 (`FOR UPDATE SKIP LOCKED`), sempre com o mesmo `event_id`. Nenhuma conexão fica presa durante o
  publish. `customer.created` e `customer.anamnesis_updated` continuam fora do outbox. Falha no broker nunca
  quebra a requisição.
- **Consumer** (lifespan, desligado sem `RABBITMQ_URL`): idempotente por `event_id` (tabela `processed_events`).
  Só muda `EM_ANALISE` → `APROVADO`/`ANALISE_MANUAL` e guarda o resumo em `business_profiles.analise`. Uma análise
  com `source_event_id` diferente do `submission_event_id` do envio atual (análise atrasada de um envio anterior) é
  `ignored`; sem um dos dois, aplica normalmente. Erro inesperado volta para a fila uma vez.

## Métricas e logs

`GET /metrics` (público; o gateway não o expõe). Séries rotuladas começam zeradas.

| Métrica                                       | Tipo      | Descrição                                                         |
| --------------------------------------------- | --------- | ----------------------------------------------------------------- |
| `http_requests_total`, `http_request_duration_seconds`, `http_request_duration_highr_seconds` | padrão | Instrumentação HTTP (`prometheus-fastapi-instrumentator`) |
| `customers_created_total`                     | counter   | Clientes PF criados                                               |
| `events_published_total{routing_key,result}`  | counter   | Publicações (`ok`, `error`)                                       |
| `events_consumed_total{routing_key,result}`   | counter   | Consumo (`ok`, `duplicate`, `ignored`, `invalid`, `error`)        |
| `onboarding_submissions_total{segmento}`      | counter   | Envios para análise (9 segmentos)                                 |
| `onboarding_drafts_saved_total`               | counter   | Rascunhos salvos                                                  |
| `onboarding_reviews_total{decisao}`           | counter   | Decisões manuais (`APROVADO`, `REPROVADO`)                        |
| `onboarding_manual_queue_size`                | gauge     | Empresas em `ANALISE_MANUAL` (lido do banco no startup)           |
| `outbox_pending`                              | gauge     | Eventos do outbox ainda não publicados                            |
| `team_members_total{papel,status}`            | gauge     | Membros por papel e status (15 séries)                            |

Logs em JSON com `X-Request-ID` (reaproveitado do gateway ou gerado, e devolvido na resposta). Detalhes e payloads
em [docs/observability-events.md](docs/observability-events.md).

## Autenticação e autorização (Auth0)

Envie o access token do Auth0 em `Authorization: Bearer <token>`. A API valida a assinatura RS256 via JWKS, o
issuer, a audience, a expiração e o `sub`:

- sem token ou com token inválido: **401** (`WWW-Authenticate: Bearer`);
- token sem a permissão da rota: **403** `{"detail": "Missing permission: <permissão>"}` (claim `permissions` do RBAC
  do Auth0, ou `scope` em tokens machine-to-machine);
- `AUTH0_*` não configurado: **503** (nenhuma rota de negócio fica liberada).

Permissões do portal: `read:self` e `write:self` (perfil `cliente`) e `review:onboarding` (analista e admin). As
permissões finas da empresa (`ver_financeiro`, `pagar`...) ficam em `company_members`, não no token. O Credit Score
chama `GET /customers/{id}` e `GET /me` repassando o token do usuário (token relay). Detalhes em
[docs/auth.md](docs/auth.md).

## Produção (EC2 + API Gateway)

Roda no `docker compose` da infraestrutura na EC2 `3.235.6.136`, **sem porta publicada**: o acesso público é pelo
API Gateway (nginx) na porta **8080** com o prefixo `/onboarding` (removido antes de chegar aqui; `ROOT_PATH=/onboarding`
só para o Swagger). O banco é o Postgres gerenciado da Aiven (SSL, `DB_POOL_SIZE=2`, `DB_MAX_OVERFLOW=1`).

| O quê          | URL                                                                                 |
| -------------- | ----------------------------------------------------------------------------------- |
| API            | `http://3.235.6.136:8080/onboarding/...` (ex.: `/onboarding/health`)                |
| Swagger        | `http://3.235.6.136:8080/onboarding/docs` (exige Bearer token)                      |
| Front (Vercel) | https://erp-banking-front.vercel.app → `/api/onboarding/*` reescrito para o gateway |
| Grafana        | `http://3.235.6.136:8081`                                                           |
| Prometheus     | `http://3.235.6.136:8082` (coleta `onboarding-api:8081/metrics` pela rede interna)  |
