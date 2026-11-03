"""Regras do onboarding PJ (portal do cliente)."""
import logging
import uuid
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.metrics import ONBOARDING_MANUAL_QUEUE
from app.models import BusinessProfile, Customer
from app.models.customer import TIPO_PJ
from app.schemas.onboarding import OnboardingIn
from app.templates import validate_respostas

logger = logging.getLogger(__name__)

NAO_INICIADO = "NAO_INICIADO"
RASCUNHO = "RASCUNHO"
EM_ANALISE = "EM_ANALISE"
ANALISE_MANUAL = "ANALISE_MANUAL"
APROVADO = "APROVADO"
REPROVADO = "REPROVADO"

# Status persistidos (NAO_INICIADO só existe na resposta, quando não há customer)
STATUSES = (RASCUNHO, EM_ANALISE, ANALISE_MANUAL, APROVADO, REPROVADO)

# Status a partir dos quais o cliente pode editar/reenviar o onboarding
EDITABLE_STATUSES = (None, RASCUNHO, REPROVADO)

# Campos de `empresa` exigidos no envio (nome_fantasia, fundacao_ano e funcionarios são opcionais)
EMPRESA_OBRIGATORIOS = ("razao_social", "cnpj", "email", "telefone", "cidade", "estado")


NOME_MAX = Customer.__table__.c.nome.type.length  # razao_social aceita 160; nome é VARCHAR(120)


class OnboardingConflictError(Exception):
    pass


class OnboardingValidationError(Exception):
    def __init__(self, campos: list[dict]):
        super().__init__("Onboarding incompleto ou inválido")
        self.campos = campos


def refresh_manual_queue(db: Session) -> int | None:
    """Atualiza o gauge onboarding_manual_queue_size com a contagem de ANALISE_MANUAL.

    Roda depois do commit: uma falha aqui só é logada (não pode virar 500 nem impedir a
    publicação do evento de algo que já foi gravado).
    """
    try:
        size = db.scalar(
            select(func.count()).select_from(Customer)
            .where(Customer.onboarding_status == ANALISE_MANUAL)
        ) or 0
        ONBOARDING_MANUAL_QUEUE.set(size)
    except Exception:
        logger.exception("Falha ao atualizar onboarding_manual_queue_size")
        db.rollback()
        return None
    return size


def claim_status(db: Session, customer_id: int, allowed: tuple, new_status: str) -> bool:
    """Compare-and-set do onboarding_status: só muda se o status atual (no banco) estiver em
    `allowed`. False quando outra transação já mudou o status (decisão/envio concorrente)."""
    current = Customer.onboarding_status
    conditions = [current.in_([s for s in allowed if s is not None])]
    if None in allowed:
        conditions.append(current.is_(None))
    result = db.execute(
        update(Customer)
        .where(Customer.id == customer_id, or_(*conditions))
        .values(onboarding_status=new_status)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


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


def onboarding_view(customer: Customer | None) -> dict:
    if customer is None:
        return {
            "empresa": None, "segmento": None, "respostas": {}, "observacoes": None,
            "onboarding_status": NAO_INICIADO, "updated_at": None,
            "review_comment": None, "reviewed_at": None,
        }
    profile = customer.business_profile
    # comentário/data da revisão só aparecem após decisão manual (APROVADO/REPROVADO)
    reviewed = (
        profile is not None
        and customer.onboarding_status in (APROVADO, REPROVADO)
        and profile.reviewed_at is not None
    )
    return {
        "empresa": empresa_dict(customer),
        "segmento": profile.segmento if profile else customer.segmento,
        "respostas": (profile.respostas if profile else None) or {},
        "observacoes": profile.observacoes if profile else None,
        "onboarding_status": customer.onboarding_status or NAO_INICIADO,
        "updated_at": profile.updated_at if profile else None,
        "review_comment": profile.review_comment if reviewed else None,
        "reviewed_at": profile.reviewed_at if reviewed else None,
    }


def submission_errors(data: OnboardingIn) -> list[dict]:
    """Validação completa do envio: obrigatórios da empresa, segmento e respostas do template."""
    empresa = data.empresa.model_dump()
    erros = [
        {"campo": f"empresa.{campo}", "erro": "Campo obrigatório."}
        for campo in EMPRESA_OBRIGATORIOS
        if empresa.get(campo) is None
    ]
    if data.segmento is None:
        erros.append({"campo": "segmento", "erro": "Escolha o segmento."})
    else:
        erros.extend(validate_respostas(data.segmento, data.respostas))
    return erros


class OnboardingService:
    def __init__(self, db: Session):
        self.db = db

    def save(self, sub: str, data: OnboardingIn) -> Customer:
        """Cria/atualiza o customer PJ do `sub` (substitui o estado salvo pelo corpo recebido).

        enviar=false → RASCUNHO; enviar=true → valida tudo e vai para EM_ANALISE.
        Erros: OnboardingConflictError (status não editável ou CNPJ de outro cliente) e
        OnboardingValidationError (envio incompleto).
        """
        customer = find_by_sub(self.db, sub)
        if customer is not None and customer.onboarding_status not in EDITABLE_STATUSES:
            raise OnboardingConflictError(
                f"Onboarding em {customer.onboarding_status} não pode ser alterado"
            )
        empresa = data.empresa
        if empresa.cnpj is not None:
            owner = self.db.scalar(select(Customer.id).where(Customer.cnpj == empresa.cnpj))
            if owner is not None and (customer is None or owner != customer.id):
                raise OnboardingConflictError(f"CNPJ {empresa.cnpj} já cadastrado")
        if data.enviar:
            erros = submission_errors(data)
            if erros:
                raise OnboardingValidationError(erros)
        new_status = EM_ANALISE if data.enviar else RASCUNHO
        if customer is not None and not claim_status(
            self.db, customer.id, EDITABLE_STATUSES, new_status
        ):
            raise OnboardingConflictError("Onboarding alterado por outra requisição; recarregue")

        if customer is None:
            customer = Customer(auth0_sub=sub, tipo_pessoa=TIPO_PJ)
            self.db.add(customer)
        profile = customer.business_profile
        if profile is None:
            profile = BusinessProfile(respostas={})
            customer.business_profile = profile

        customer.tipo_pessoa = TIPO_PJ
        customer.cpf = None
        customer.nome = (empresa.razao_social or "")[:NOME_MAX]
        customer.razao_social = empresa.razao_social
        customer.nome_fantasia = empresa.nome_fantasia
        customer.cnpj = empresa.cnpj
        customer.email = empresa.email or ""
        customer.telefone = empresa.telefone or ""
        customer.segmento = data.segmento
        profile.segmento = data.segmento
        profile.cidade = empresa.cidade
        profile.estado = empresa.estado
        profile.fundacao_ano = empresa.fundacao_ano
        profile.funcionarios = empresa.funcionarios
        profile.respostas = dict(data.respostas)
        profile.observacoes = data.observacoes
        profile.updated_at = datetime.utcnow()

        customer.onboarding_status = new_status
        if data.enviar:
            profile.submitted_at = datetime.utcnow()
            # event_id do customer.onboarding_submitted desta submissão (análises de outra são ignoradas)
            profile.submission_event_id = str(uuid.uuid4())
            # reenvio após REPROVADO: a análise e a revisão anteriores deixam de valer
            profile.analise = None
            profile.reviewed_by = profile.review_comment = profile.reviewed_at = None

        try:
            self.db.commit()
        except IntegrityError as exc:  # corrida com outro envio do mesmo sub/CNPJ
            self.db.rollback()
            raise OnboardingConflictError("Onboarding já cadastrado para este usuário ou CNPJ") from exc
        self.db.refresh(customer)
        refresh_manual_queue(self.db)
        return customer
