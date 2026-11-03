from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config.database import get_db
from app.core.metrics import ONBOARDING_REVIEWS
from app.core.security import Principal, require_permission
from app.events import ONBOARDING_REVIEWED, EventPublisher, get_publisher, onboarding_reviewed_event
from app.models import BusinessProfile, Customer
from app.schemas.me import EmpresaOut
from app.services.onboarding_service import ANALISE_MANUAL, empresa_dict, refresh_manual_queue

router = APIRouter(prefix="/onboarding/reviews", tags=["onboarding-review"])

ReviewStatus = Literal["RASCUNHO", "EM_ANALISE", "ANALISE_MANUAL", "APROVADO", "REPROVADO"]


class ReviewItem(BaseModel):
    customer_id: int
    empresa: EmpresaOut
    segmento: str | None
    observacoes: str | None
    analise: dict | None
    submitted_at: datetime | None


class DecisionIn(BaseModel):
    decisao: Literal["APROVADO", "REPROVADO"]
    comentario: str | None = Field(default=None, max_length=2000)


class DecisionOut(BaseModel):
    customer_id: int
    onboarding_status: str
    decisao: str
    comentario: str | None
    reviewer: str
    reviewed_at: datetime


@router.get("", response_model=list[ReviewItem])
def list_reviews(
    status: ReviewStatus = Query(default=ANALISE_MANUAL),
    _: Principal = Depends(require_permission("review:onboarding")),
    db: Session = Depends(get_db),
):
    """Fila de análise. `analise` é o resumo do evento do Score; o detalhe completo fica em
    Score `GET /scores/analyses/{customer_id}` (não chamamos o Score de forma síncrona)."""
    customers = db.scalars(
        select(Customer)
        .join(BusinessProfile)
        .options(selectinload(Customer.business_profile))
        .where(Customer.onboarding_status == status)
        .order_by(BusinessProfile.submitted_at.asc(), Customer.id.asc())
    )
    return [
        {
            "customer_id": c.id,
            "empresa": empresa_dict(c),
            "segmento": c.business_profile.segmento,
            "observacoes": c.business_profile.observacoes,
            "analise": c.business_profile.analise,
            "submitted_at": c.business_profile.submitted_at,
        }
        for c in customers
    ]


@router.post("/{customer_id}/decision", response_model=DecisionOut)
def decide(
    customer_id: int,
    payload: DecisionIn,
    background: BackgroundTasks,
    principal: Principal = Depends(require_permission("review:onboarding")),
    db: Session = Depends(get_db),
    publisher: EventPublisher = Depends(get_publisher),
):
    customer = db.get(Customer, customer_id)
    if customer is None or customer.business_profile is None:
        raise HTTPException(404, f"Onboarding do cliente {customer_id} não encontrado")
    if customer.onboarding_status != ANALISE_MANUAL:
        raise HTTPException(
            409, f"Decisão só é permitida em {ANALISE_MANUAL} (status atual: {customer.onboarding_status})"
        )
    profile = customer.business_profile
    customer.onboarding_status = payload.decisao
    profile.reviewed_by = principal.subject
    profile.review_comment = payload.comentario
    profile.reviewed_at = datetime.utcnow()
    db.commit()
    ONBOARDING_REVIEWS.labels(decisao=payload.decisao).inc()
    refresh_manual_queue(db)
    background.add_task(
        publisher.publish,
        ONBOARDING_REVIEWED,
        onboarding_reviewed_event(customer_id, payload.decisao, payload.comentario, principal.subject),
    )
    return {
        "customer_id": customer_id,
        "onboarding_status": customer.onboarding_status,
        "decisao": payload.decisao,
        "comentario": payload.comentario,
        "reviewer": principal.subject,
        "reviewed_at": profile.reviewed_at,
    }
