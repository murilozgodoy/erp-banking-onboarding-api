from unittest.mock import MagicMock

from sqlalchemy import inspect

from app.config.migrations import migration_statements, run_migrations


def test_sqlite_is_noop(engine):
    assert migration_statements("sqlite") == []
    run_migrations(engine)  # não executa nada
    columns = {c["name"]: c for c in inspect(engine).get_columns("customers")}
    assert columns["cpf"]["nullable"] is True
    assert {"auth0_sub", "tipo_pessoa", "cnpj", "razao_social", "nome_fantasia",
            "segmento", "onboarding_status"} <= set(columns)
    assert "business_profiles" in inspect(engine).get_table_names()


def test_postgres_statements_are_idempotent():
    statements = migration_statements("postgresql")
    adds = [s for s in statements if "ADD COLUMN" in s]
    assert len(adds) == 8
    assert all("ADD COLUMN IF NOT EXISTS" in s for s in adds)
    assert "ALTER TABLE customers ADD COLUMN IF NOT EXISTS tipo_pessoa VARCHAR(2) NOT NULL DEFAULT 'PF'" in statements
    assert "ALTER TABLE customers ALTER COLUMN cpf DROP NOT NULL" in statements
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ix_customers_auth0_sub ON customers (auth0_sub)" in statements
    assert "CREATE UNIQUE INDEX IF NOT EXISTS ix_customers_cnpj ON customers (cnpj)" in statements


def test_run_migrations_executes_on_postgres():
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    conn = engine.begin.return_value.__enter__.return_value
    run_migrations(engine)
    executed = [str(call.args[0]) for call in conn.execute.call_args_list]
    assert executed == migration_statements("postgresql")
