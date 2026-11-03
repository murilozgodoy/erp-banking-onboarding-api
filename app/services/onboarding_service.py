"""Regras do onboarding PJ (portal do cliente)."""
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Customer

NAO_INICIADO = "NAO_INICIADO"
RASCUNHO = "RASCUNHO"
EM_ANALISE = "EM_ANALISE"
ANALISE_MANUAL = "ANALISE_MANUAL"
APROVADO = "APROVADO"
REPROVADO = "REPROVADO"


def _blank_to_none(value):
    return value if value not in ("", None) else None


def empresa_dict(customer: Customer) -> dict:
    """Monta `empresa` a partir de customers (identificação/contato) + business_profiles."""
    profile = customer.business_profile
    return {
        "razao_social": _blank_to_none(customer.razao_social),
        "nome_fantasia": _blank_to_none(customer.nome_fantasia),
        "cnpj": _blank_to_none(customer.cnpj),
        "email": _blank_to_none(customer.email),
        "telefone": _blank_to_none(customer.telefone),
        "cidade": profile.cidade if profile else None,
        "estado": profile.estado if profile else None,
        "fundacao_ano": profile.fundacao_ano if profile else None,
        "funcionarios": profile.funcionarios if profile else None,
    }


def find_by_sub(db: Session, sub: str) -> Customer | None:
    return db.scalar(
        select(Customer)
        .options(selectinload(Customer.business_profile))
        .where(Customer.auth0_sub == sub)
    )


def me_view(db: Session, sub: str) -> dict:
    customer = find_by_sub(db, sub)
    if customer is None:
        return {"customer_id": None, "onboarding_status": NAO_INICIADO, "empresa": None}
    return {
        "customer_id": customer.id,
        "onboarding_status": customer.onboarding_status or NAO_INICIADO,
        "empresa": empresa_dict(customer),
    }
