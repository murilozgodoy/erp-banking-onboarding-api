"""Resolver único do `sub` do token para a empresa (customer) e o membro da equipe.

Usado pelo `GET /me` (que Score e Transactions chamam com o token repassado) e por todas as rotas `/me`.

1. `customers.auth0_sub == sub` → dono da empresa (fonte da verdade da posse). O DONO em `company_members`
   é criado/sincronizado sob demanda (`ensure_owner_member`).
2. Senão, `company_members.auth0_sub == sub` (papel diferente de DONO) → membro da empresa:
   ATIVO resolve para o customer da empresa; SUSPENSO → 403 `{"error":"MEMBRO_SUSPENSO"}`.
3. Nada → sem empresa (`NAO_INICIADO`, `membro: null`).
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import ApiError
from app.models import CompanyMember, Customer
from app.services.onboarding_service import NAO_INICIADO, empresa_dict, find_by_sub
from app.team.members import ensure_owner_member, member_view
from app.team.permissions import ATIVO, DONO, DONO_PERMISSAO, SUSPENSO

MEMBRO_SUSPENSO = "MEMBRO_SUSPENSO"
SEM_PERMISSAO = "SEM_PERMISSAO"


@dataclass(frozen=True)
class Membership:
    customer: Customer | None
    member: CompanyMember | None

    @property
    def is_owner(self) -> bool:
        return self.member is not None and self.member.papel == DONO


def resolve(db: Session, sub: str) -> Membership:
    """Empresa e membro do `sub`. Levanta ApiError 403 MEMBRO_SUSPENSO para membro suspenso."""
    customer = find_by_sub(db, sub)
    if customer is not None:
        return Membership(customer, ensure_owner_member(db, customer))
    member = db.scalar(
        select(CompanyMember).where(CompanyMember.auth0_sub == sub, CompanyMember.papel != DONO)
    )
    if member is None:
        return Membership(None, None)
    if member.status == SUSPENSO:
        raise ApiError(403, MEMBRO_SUSPENSO)
    if member.status != ATIVO:  # pragma: no cover - o sub só é gravado no aceite (que já ativa)
        return Membership(None, None)
    customer = db.scalar(
        select(Customer).options(selectinload(Customer.business_profile))
        .where(Customer.id == member.customer_id)
    )
    return Membership(customer, member)


def require_owner(membership: Membership) -> None:
    """Ações só do dono (ex.: PUT /me/onboarding): membro que não é DONO → 403 SEM_PERMISSAO/dono.

    Sem empresa ainda (`member is None`) é permitido: é quem está criando a empresa.
    """
    if membership.member is not None and membership.member.papel != DONO:
        raise ApiError(403, SEM_PERMISSAO, permissao=DONO_PERMISSAO)


def me_view(db: Session, sub: str) -> dict:
    membership = resolve(db, sub)
    customer = membership.customer
    if customer is None:
        return {"customer_id": None, "onboarding_status": NAO_INICIADO, "empresa": None, "membro": None}
    return {
        "customer_id": customer.id,
        "onboarding_status": customer.onboarding_status or NAO_INICIADO,
        "empresa": empresa_dict(customer),
        "membro": member_view(membership.member),
    }
