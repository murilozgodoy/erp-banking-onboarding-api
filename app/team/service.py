"""Gestão da equipe da empresa: convite, aceite, edição e remoção de membros.

Regras (PORTAL_CLIENTE.md, seção 11, e decisões documentadas no README):
- Todas as ações, menos o aceite, exigem um membro ATIVO com `gerenciar_equipe`.
- Exatamente um DONO por empresa: o DONO não é convidável, editável, suspenso nem removido, e ninguém é
  promovido a DONO na v1. Todo UPDATE/DELETE leva `papel <> 'DONO'` no WHERE (compare-and-set), então
  nenhuma corrida consegue tirar o DONO da empresa.
- Ninguém edita nem remove a si mesmo (evita autoescalada de papel, permissões ou limite).
- Quem não é DONO só concede permissões que ele mesmo tem, só define `limite_pagamento` até o próprio (null só
  se o dele for null) e só gerencia, convida ou atribui papéis abaixo do seu (DONO > ADMIN > FINANCEIRO >
  OPERADOR > LEITURA).
- Edição com compare-and-set em `updated_at` (otimista): duas edições simultâneas → a segunda recebe 409.
- O token do convite é `secrets.token_urlsafe(32)`, guardado só como sha256 e válido por 7 dias; aparece
  apenas no `convite_url` da resposta de criação.
- Cada mudança grava `company.member_changed` no outbox na mesma transação.
"""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import case, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.core.errors import ApiError
from app.events.outbox import enqueue
from app.events.publisher import MEMBER_CHANGED, member_changed_event
from app.models import CompanyMember, Customer
from app.schemas.team import InviteIn, MemberPatch
from app.team.members import refresh_team_members
from app.team.permissions import (
    ATIVO,
    CONVIDADO,
    DONO,
    DONO_PERMISSAO,
    PAPEIS,
    GERENCIAR_EQUIPE,
    SUSPENSO,
    canonical,
    effective,
    preset,
)
from app.team.resolver import MEMBRO_SUSPENSO, SEM_PERMISSAO, Membership

logger = logging.getLogger(__name__)

INVITE_TTL = timedelta(days=7)
DEFAULT_FRONT_URL = "https://erp-banking-front.vercel.app"

# acao do evento company.member_changed
CONVIDADO_ACAO = "CONVIDADO"
ATUALIZADO = "ATUALIZADO"
SUSPENSO_ACAO = "SUSPENSO"
REATIVADO = "REATIVADO"
REMOVIDO = "REMOVIDO"
ACEITO = "ACEITO"

# códigos de erro
MEMBRO_NAO_ENCONTRADO = "MEMBRO_NAO_ENCONTRADO"
DONO_PROTEGIDO = "DONO_PROTEGIDO"
DONO_UNICO = "DONO_UNICO"
AUTO_EDICAO = "AUTO_EDICAO"
EMAIL_JA_CADASTRADO = "EMAIL_JA_CADASTRADO"
CONVITE_PENDENTE = "CONVITE_PENDENTE"
CONFLITO_CONCORRENTE = "CONFLITO_CONCORRENTE"
CONVITE_NAO_ENCONTRADO = "CONVITE_NAO_ENCONTRADO"
CONVITE_EXPIRADO = "CONVITE_EXPIRADO"
JA_VINCULADO = "JA_VINCULADO"

# pseudo-permissões dos 403 SEM_PERMISSAO de escalada
LIMITE_PERMISSAO = "limite_pagamento"
HIERARQUIA_PERMISSAO = "hierarquia"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def invite_url(token: str) -> str:
    base = (settings.front_url or DEFAULT_FRONT_URL).rstrip("/")
    return f"{base}/convite/{token}"


def team_member_view(member: CompanyMember) -> dict:
    """Item de GET /me/team (sem token, hash nem `sub`)."""
    return {
        "id": member.id,
        "nome": member.nome,
        "email": member.email,
        "papel": member.papel,
        "permissoes": effective(member.papel, member.permissoes),
        "limite_pagamento": float(member.limite_pagamento) if member.limite_pagamento is not None else None,
        "status": member.status,
        "convite_expira_em": member.invite_expires_at,
        "created_at": member.created_at,
        "updated_at": member.updated_at,
    }


def require_manager(membership: Membership) -> CompanyMember:
    """Membro ATIVO com `gerenciar_equipe` (o resolver já barrou o SUSPENSO)."""
    member = membership.member
    if (
        member is None
        or member.status != ATIVO
        or GERENCIAR_EQUIPE not in effective(member.papel, member.permissoes)
    ):
        raise ApiError(403, SEM_PERMISSAO, permissao=GERENCIAR_EQUIPE)
    return member


class TeamService:
    def __init__(self, db: Session):
        self.db = db
        # (routing_key, payload) gravados no outbox na última operação, para o publish rápido pós-commit
        self.events: list[tuple[str, dict]] = []

    # ---------- helpers ----------

    def _emit(self, customer_id: int, member_id: int, acao: str, papel: str, permissoes) -> None:
        event = member_changed_event(customer_id, member_id, acao, papel, effective(papel, permissoes))
        enqueue(self.db, MEMBER_CHANGED, event)
        self.events.append((MEMBER_CHANGED, event))

    def _commit(self) -> None:
        self.db.commit()
        refresh_team_members(self.db)

    @staticmethod
    def _check_grant(actor: CompanyMember, granted) -> None:
        """Quem não é DONO só concede permissões que ele mesmo tem."""
        if actor.papel == DONO:
            return
        held = set(effective(actor.papel, actor.permissoes))
        missing = [p for p in granted if p not in held]
        if missing:
            raise ApiError(403, SEM_PERMISSAO, permissao=missing[0])

    @staticmethod
    def _check_rank(actor: CompanyMember, papel: str) -> None:
        """Quem não é DONO só age sobre (ou atribui) papéis estritamente abaixo do seu."""
        if actor.papel == DONO:
            return
        if PAPEIS.index(papel) <= PAPEIS.index(actor.papel):
            raise ApiError(403, SEM_PERMISSAO, permissao=HIERARQUIA_PERMISSAO)

    @staticmethod
    def _check_limit(actor: CompanyMember, limite) -> None:
        """Quem não é DONO só define limite até o próprio; null (sem limite) só se o dele for null."""
        if actor.papel == DONO or actor.limite_pagamento is None:
            return
        if limite is None or Decimal(str(limite)) > Decimal(str(actor.limite_pagamento)):
            raise ApiError(403, SEM_PERMISSAO, permissao=LIMITE_PERMISSAO)

    def _target(self, actor: CompanyMember, member_id: int) -> CompanyMember:
        target = self.db.scalar(
            select(CompanyMember).where(
                CompanyMember.id == member_id, CompanyMember.customer_id == actor.customer_id
            )
        )
        if target is None:  # inclusive id de outra empresa
            raise ApiError(404, MEMBRO_NAO_ENCONTRADO)
        if target.id == actor.id:
            raise ApiError(403, AUTO_EDICAO)
        if target.papel == DONO:
            raise ApiError(403, DONO_PROTEGIDO)
        self._check_rank(actor, target.papel)
        return target

    # ---------- operações ----------

    def list(self, customer_id: int) -> list[CompanyMember]:
        """DONO primeiro, depois por ordem de criação."""
        return list(self.db.scalars(
            select(CompanyMember)
            .where(CompanyMember.customer_id == customer_id)
            .order_by(case((CompanyMember.papel == DONO, 0), else_=1), CompanyMember.id)
        ))

    def invite(self, actor: CompanyMember, data: InviteIn) -> tuple[CompanyMember, str]:
        permissoes = data.permissoes if data.permissoes is not None else preset(data.papel)
        self._check_rank(actor, data.papel)
        self._check_limit(actor, data.limite_pagamento)
        self._check_grant(actor, permissoes)
        email = data.email.lower()
        existing = self.db.scalar(
            select(CompanyMember.id).where(
                CompanyMember.customer_id == actor.customer_id, CompanyMember.email == email
            )
        )
        if existing is not None:  # inclusive SUSPENSO: reative em vez de convidar de novo
            raise ApiError(409, EMAIL_JA_CADASTRADO)
        token = secrets.token_urlsafe(32)
        member = CompanyMember(
            customer_id=actor.customer_id, auth0_sub=None, email=email, nome=data.nome,
            papel=data.papel, permissoes=canonical(permissoes), limite_pagamento=data.limite_pagamento,
            status=CONVIDADO, invite_token_hash=hash_token(token),
            invite_expires_at=datetime.utcnow() + INVITE_TTL, created_by=actor.auth0_sub,
        )
        self.events = []
        try:
            self.db.add(member)
            self.db.flush()
            self._emit(member.customer_id, member.id, CONVIDADO_ACAO, member.papel, member.permissoes)
            self._commit()
        except IntegrityError as exc:  # convite simultâneo para o mesmo e-mail
            self.events = []
            self.db.rollback()
            raise ApiError(409, EMAIL_JA_CADASTRADO) from exc
        return member, token

    def update(self, actor: CompanyMember, member_id: int, patch: MemberPatch) -> CompanyMember:
        fields = patch.model_fields_set
        target = self._target(actor, member_id)
        if patch.papel == DONO:
            if actor.papel != DONO:
                raise ApiError(403, SEM_PERMISSAO, permissao=DONO_PERMISSAO)
            raise ApiError(409, DONO_UNICO)  # sem transferência de posse na v1

        papel = patch.papel or target.papel
        if papel != target.papel:
            self._check_rank(actor, papel)
        if "limite_pagamento" in fields and patch.limite_pagamento != target.limite_pagamento:
            self._check_limit(actor, patch.limite_pagamento)
        current = canonical(target.permissoes)
        if patch.permissoes is not None:
            permissoes = patch.permissoes
        elif papel != target.papel:
            permissoes = preset(papel)  # trocar o papel sem mandar permissões aplica o preset
        else:
            permissoes = current
        limite = patch.limite_pagamento if "limite_pagamento" in fields else target.limite_pagamento
        status = patch.status or target.status
        if status != target.status and target.status == CONVIDADO:
            raise ApiError(409, CONVITE_PENDENTE)  # convite pendente: revogue com DELETE
        self._check_grant(actor, [p for p in permissoes if p not in current])

        if (papel, permissoes, limite, status) == (target.papel, current, target.limite_pagamento, target.status):
            return target  # nada mudou: sem evento
        if status == SUSPENSO and target.status != SUSPENSO:
            acao = SUSPENSO_ACAO
        elif status == ATIVO and target.status == SUSPENSO:
            acao = REATIVADO
        else:
            acao = ATUALIZADO

        self.events = []
        result = self.db.execute(
            update(CompanyMember)
            .where(
                CompanyMember.id == target.id,
                CompanyMember.customer_id == actor.customer_id,
                CompanyMember.papel != DONO,
                CompanyMember.updated_at == target.updated_at,  # compare-and-set otimista
            )
            .values(papel=papel, permissoes=permissoes, limite_pagamento=limite, status=status,
                    updated_at=datetime.utcnow())
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            self.db.rollback()
            raise ApiError(409, CONFLITO_CONCORRENTE)
        self._emit(actor.customer_id, target.id, acao, papel, permissoes)
        self._commit()
        self.db.refresh(target)
        return target

    def remove(self, actor: CompanyMember, member_id: int) -> None:
        """Revoga o convite ou remove o membro (nunca o DONO)."""
        target = self._target(actor, member_id)
        customer_id, papel, permissoes = target.customer_id, target.papel, list(target.permissoes or [])
        self.events = []
        result = self.db.execute(
            delete(CompanyMember)
            .where(
                CompanyMember.id == member_id,
                CompanyMember.customer_id == actor.customer_id,
                CompanyMember.papel != DONO,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:  # removido por outra requisição
            self.db.rollback()
            raise ApiError(404, MEMBRO_NAO_ENCONTRADO)
        self._emit(customer_id, member_id, REMOVIDO, papel, permissoes)
        self.db.expunge(target)
        self._commit()

    def _accepted_by(self, sub: str) -> CompanyMember:
        """Token desconhecido: se o `sub` já aceitou um convite, devolve o vínculo (aceite idempotente)."""
        member = self.db.scalar(
            select(CompanyMember)
            .where(CompanyMember.auth0_sub == sub, CompanyMember.papel != DONO)
            .execution_options(populate_existing=True)
        )
        if member is None:
            raise ApiError(404, CONVITE_NAO_ENCONTRADO)
        if member.status == SUSPENSO:
            raise ApiError(403, MEMBRO_SUSPENSO)
        return member

    def accept(self, sub: str, token: str) -> CompanyMember:
        token_hash = hash_token(token)
        member = self.db.scalar(select(CompanyMember).where(CompanyMember.invite_token_hash == token_hash))
        if member is None or member.status != CONVIDADO:
            return self._accepted_by(sub)
        if member.invite_expires_at is not None and member.invite_expires_at < datetime.utcnow():
            raise ApiError(410, CONVITE_EXPIRADO)
        owner = self.db.scalar(select(Customer.id).where(Customer.auth0_sub == sub))
        linked = self.db.scalar(select(CompanyMember.id).where(CompanyMember.auth0_sub == sub))
        if owner is not None or linked is not None:
            raise ApiError(409, JA_VINCULADO)

        self.events = []
        try:
            result = self.db.execute(
                update(CompanyMember)
                .where(
                    CompanyMember.id == member.id,
                    CompanyMember.invite_token_hash == token_hash,
                    CompanyMember.status == CONVIDADO,
                )
                .values(auth0_sub=sub, status=ATIVO, invite_token_hash=None, invite_expires_at=None,
                        updated_at=datetime.utcnow())
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:  # aceite concorrente do mesmo convite
                self.db.rollback()
                return self._accepted_by(sub)
            self._emit(member.customer_id, member.id, ACEITO, member.papel, member.permissoes)
            self._commit()
        except IntegrityError as exc:  # o sub virou dono/membro em paralelo (índice único de auth0_sub)
            self.events = []
            self.db.rollback()
            raise ApiError(409, JA_VINCULADO) from exc
        self.db.refresh(member)
        return member
