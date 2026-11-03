"""Migração idempotente executada no startup, depois do create_all.

`Base.metadata.create_all` cria tabelas novas (ex.: business_profiles) mas não altera tabelas
existentes. Em PostgreSQL (produção já tem `customers`) aplicamos as colunas da Fase 2 com
`ADD COLUMN IF NOT EXISTS`, tornamos o cpf opcional (clientes PJ não têm CPF) e criamos os
índices únicos. Em SQLite (dev/testes) o create_all já cria o schema completo: no-op.
"""
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

CUSTOMER_COLUMNS: tuple[tuple[str, str], ...] = (
    ("auth0_sub", "VARCHAR(128)"),
    ("tipo_pessoa", "VARCHAR(2) NOT NULL DEFAULT 'PF'"),
    ("cnpj", "VARCHAR(14)"),
    ("razao_social", "VARCHAR(160)"),
    ("nome_fantasia", "VARCHAR(160)"),
    ("segmento", "VARCHAR(40)"),
    ("onboarding_status", "VARCHAR(20)"),
)

UNIQUE_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_customers_auth0_sub", "auth0_sub"),
    ("ix_customers_cnpj", "cnpj"),
)


def migration_statements(dialect: str) -> list[str]:
    """SQL a executar para o dialeto informado (lista vazia = nada a fazer)."""
    if dialect != "postgresql":
        return []
    statements = [
        f"ALTER TABLE customers ADD COLUMN IF NOT EXISTS {name} {ddl}"
        for name, ddl in CUSTOMER_COLUMNS
    ]
    statements.append("ALTER TABLE customers ALTER COLUMN cpf DROP NOT NULL")
    statements.extend(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {index} ON customers ({column})"
        for index, column in UNIQUE_INDEXES
    )
    return statements


def run_migrations(engine: Engine) -> None:
    """Aplica as migrações numa única transação; idempotente."""
    statements = migration_statements(engine.dialect.name)
    if not statements:
        return
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))
    logger.info("Migrações da Fase 2 aplicadas (%d comandos)", len(statements))
