from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.config.database import Base

# Índices parciais: PostgreSQL e SQLite aceitam `CREATE UNIQUE INDEX ... WHERE ...`
_UM_DONO = "papel = 'DONO'"
_ATIVO_OU_CONVIDADO = "status IN ('CONVIDADO', 'ATIVO')"


class CompanyMember(Base):
    """Membro da equipe de uma empresa (customer PJ) e suas permissões finas.

    - `auth0_sub` é nulo até o convite ser aceito (e no DONO de um cliente semeado sem `sub`). Índice único
      comum: PostgreSQL e SQLite aceitam vários NULL num índice único.
    - Exatamente um DONO por empresa (índice único parcial em `customer_id WHERE papel = 'DONO'`). A posse
      vem de `customers.auth0_sub` (fonte da verdade); o `auth0_sub` do DONO é sincronizado pelo resolver.
    - `email` é único por empresa entre membros ATIVO/CONVIDADO (índice parcial) e guardado em minúsculas.
    - `invite_token_hash` = sha256 (hex) do token do convite; o token em si nunca é guardado.
    - `limite_pagamento` nulo = sem limite.
    """

    __tablename__ = "company_members"
    __table_args__ = (
        Index("ix_company_members_customer_id", "customer_id"),
        Index("ux_company_members_auth0_sub", "auth0_sub", unique=True),
        Index("ux_company_members_invite_token_hash", "invite_token_hash", unique=True),
        Index(
            "ux_company_members_dono", "customer_id", unique=True,
            sqlite_where=text(_UM_DONO), postgresql_where=text(_UM_DONO),
        ),
        Index(
            "ux_company_members_customer_email", "customer_id", "email", unique=True,
            sqlite_where=text(_ATIVO_OU_CONVIDADO), postgresql_where=text(_ATIVO_OU_CONVIDADO),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    auth0_sub: Mapped[str | None] = mapped_column(String(128), nullable=True)
    email: Mapped[str] = mapped_column(String(120), nullable=False)
    nome: Mapped[str] = mapped_column(String(160), nullable=False)
    papel: Mapped[str] = mapped_column(String(20), nullable=False)
    permissoes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    limite_pagamento: Mapped[float | None] = mapped_column(
        Numeric(14, 2, asdecimal=False), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    invite_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    invite_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
