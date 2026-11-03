"""Acesso a company_members: DONO de cada empresa (migração e auto-correção) e a visão do membro."""
import logging
from datetime import datetime

from sqlalchemy import DateTime, String, case, exists, func, insert, literal, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.types import JSON

from app.core.metrics import TEAM_MEMBERS
from app.models import CompanyMember, Customer
from app.models.customer import TIPO_PJ
from app.team.permissions import ATIVO, DONO, PAPEIS, STATUSES, effective, preset

logger = logging.getLogger(__name__)

CREATED_BY_MIGRATION = "migracao"


def _insert(dialect: str):
    """INSERT com ON CONFLICT DO NOTHING (PostgreSQL e SQLite); outros dialetos: INSERT simples."""
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    else:  # pragma: no cover - só PostgreSQL (produção) e SQLite (dev/testes) são usados
        return insert(CompanyMember.__table__), False
    return dialect_insert(CompanyMember.__table__), True


def owner_backfill_statement(dialect: str, customer_id: int | None = None):
    """INSERT ... SELECT ... WHERE NOT EXISTS que cria o DONO das empresas PJ que ainda não têm um.

    - Inclui clientes com `auth0_sub` nulo (ex.: semeados direto no banco): o DONO nasce com `auth0_sub` nulo
      e o resolver sincroniza quando o `customers.auth0_sub` for preenchido.
    - Se o `sub` do cliente já está em outro membro (caso anômalo), o DONO nasce sem `sub` em vez de falhar.
    - `ON CONFLICT DO NOTHING`: réplicas concorrentes no boot (ou duas requisições) não duplicam nem quebram;
      o índice único parcial `ux_company_members_dono` garante um DONO por empresa.
    """
    c = Customer.__table__
    m = CompanyMember.__table__
    other = m.alias("other_member")
    now = datetime.utcnow()
    sub_in_use = exists().where(other.c.auth0_sub == c.c.auth0_sub)
    query = (
        select(
            c.c.id,
            case((sub_in_use, None), else_=c.c.auth0_sub),
            func.lower(c.c.email),
            func.coalesce(func.nullif(c.c.razao_social, ""), func.nullif(c.c.nome, ""), "Dono"),
            literal(DONO, String),
            literal(preset(DONO), JSON),
            literal(ATIVO, String),
            literal(CREATED_BY_MIGRATION, String),
            literal(now, DateTime),
            literal(now, DateTime),
        )
        .where(
            c.c.tipo_pessoa == TIPO_PJ,
            ~exists().where(m.c.customer_id == c.c.id, m.c.papel == DONO),
        )
        .order_by(c.c.id)  # mesma ordem em réplicas concorrentes (evita deadlock)
    )
    if customer_id is not None:
        query = query.where(c.c.id == customer_id)
    stmt, upsert = _insert(dialect)
    stmt = stmt.from_select(
        ["customer_id", "auth0_sub", "email", "nome", "papel", "permissoes", "status",
         "created_by", "created_at", "updated_at"],
        query,
    )
    return stmt.on_conflict_do_nothing() if upsert else stmt


def backfill_owner_members(conn: Connection, dialect: str) -> int:
    """Cria o DONO de cada empresa PJ sem DONO. Idempotente e barato (NOT EXISTS indexado)."""
    result = conn.execute(owner_backfill_statement(dialect))
    return max(int(result.rowcount or 0), 0)


def refresh_team_members(db: Session) -> None:
    """Gauge team_members_total{papel,status} a partir do banco (uma consulta agrupada).

    Roda depois do commit: uma falha só é logada (não pode virar 500 de algo que já foi gravado).
    """
    try:
        rows = db.execute(
            select(CompanyMember.papel, CompanyMember.status, func.count())
            .group_by(CompanyMember.papel, CompanyMember.status)
        ).all()
    except Exception:
        logger.exception("Falha ao atualizar team_members_total")
        db.rollback()
        return
    counts = {(papel, status): total for papel, status, total in rows}
    for papel in PAPEIS:
        for status in STATUSES:
            TEAM_MEMBERS.labels(papel=papel, status=status).set(counts.get((papel, status), 0))


def find_dono(db: Session, customer_id: int) -> CompanyMember | None:
    return db.scalar(
        select(CompanyMember)
        .where(CompanyMember.customer_id == customer_id, CompanyMember.papel == DONO)
        .execution_options(populate_existing=True)
    )


def ensure_owner_member(db: Session, customer: Customer) -> CompanyMember | None:
    """DONO da empresa cujo dono é `customers.auth0_sub` (fonte da verdade da posse).

    Cria o DONO se faltar e sincroniza o `auth0_sub` dele com o do customer (ex.: cliente semeado e
    `auth0_sub` preenchido depois por UPDATE manual). Transação curta, idempotente e segura sob concorrência:
    o INSERT usa ON CONFLICT DO NOTHING e, em conflito de índice único, desfaz e relê.
    """
    customer_id, sub = customer.id, customer.auth0_sub
    dono = find_dono(db, customer_id)
    for _ in range(2):
        if dono is not None and dono.auth0_sub == sub:
            return dono
        try:
            if sub is not None:
                # `customers.auth0_sub` é único: outro DONO com este sub é resto de uma troca manual de dono
                db.execute(
                    update(CompanyMember)
                    .where(CompanyMember.auth0_sub == sub, CompanyMember.papel == DONO,
                           CompanyMember.customer_id != customer_id)
                    .values(auth0_sub=None, updated_at=datetime.utcnow())
                    .execution_options(synchronize_session=False)
                )
            if dono is None:
                db.execute(owner_backfill_statement(db.get_bind().dialect.name, customer_id))
            else:
                db.execute(
                    update(CompanyMember)
                    .where(CompanyMember.id == dono.id, CompanyMember.papel == DONO)
                    .values(auth0_sub=sub, updated_at=datetime.utcnow())
                    .execution_options(synchronize_session=False)
                )
            db.commit()
            refresh_team_members(db)
        except IntegrityError:
            db.rollback()  # outra requisição venceu ou o sub está em outro membro: relê
        dono = find_dono(db, customer_id)
    if dono is not None and dono.auth0_sub != sub:
        logger.warning("DONO do customer %s sem o auth0_sub do dono (sub em uso por outro membro)", customer_id)
    return dono


def member_view(member: CompanyMember | None) -> dict | None:
    """`membro` do GET /me. `limite_pagamento` é número ou null; permissões efetivas (DONO = todas)."""
    if member is None:
        return None
    return {
        "id": member.id,
        "nome": member.nome,
        "email": member.email,
        "papel": member.papel,
        "permissoes": effective(member.papel, member.permissoes),
        "limite_pagamento": float(member.limite_pagamento) if member.limite_pagamento is not None else None,
        "status": member.status,
    }
