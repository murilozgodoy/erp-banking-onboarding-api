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
