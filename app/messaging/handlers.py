"""Handlers dos eventos consumidos (síncronos, testáveis sem broker)."""
import logging
from typing import Literal

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.models import BusinessProfile, Customer, ProcessedEvent
from app.services.onboarding_service import EM_ANALISE, refresh_manual_queue

logger = logging.getLogger(__name__)

ANALYSIS_COMPLETED = "business.analysis_completed"

RESULT_OK = "ok"
RESULT_DUPLICATE = "duplicate"
RESULT_IGNORED = "ignored"
RESULT_INVALID = "invalid"


class AnalysisCompletedEvent(BaseModel):
    event_id: str
    event_type: str = ANALYSIS_COMPLETED
    customer_id: int
    status: Literal["APROVADO", "ANALISE_MANUAL"]
    score: float | None = None
    faixa_risco: str | None = None
    gerado_por: str | None = None
    # event_id do customer.onboarding_submitted que gerou a análise (ausente em Score antigo)
    source_event_id: str | None = None


def _is_stale(profile: BusinessProfile | None, source_event_id: str | None) -> bool:
    current = profile.submission_event_id if profile is not None else None
    return bool(source_event_id and current and source_event_id != current)


def handle_analysis_completed(db: Session, payload: dict) -> str:
    """Move EM_ANALISE → APROVADO|ANALISE_MANUAL e guarda o resumo da análise.

    Idempotente por `event_id` (tabela processed_events). Customer inexistente, fora de
    EM_ANALISE ou análise de outra submissão (`source_event_id` diferente do
    `submission_event_id` gravado) → `ignored` (o evento também é registrado, para não ser
    reprocessado). Sem `source_event_id` (Score antigo) ou sem `submission_event_id` (envio
    anterior a este campo) não há com o que comparar: aplica como antes.
    """
    try:
        event = AnalysisCompletedEvent.model_validate(payload)
    except ValidationError as exc:
        logger.warning("evento %s inválido: %s", ANALYSIS_COMPLETED, exc.errors())
        return RESULT_INVALID

    if db.get(ProcessedEvent, event.event_id) is not None:
        return RESULT_DUPLICATE

    customer = db.get(Customer, event.customer_id)
    if customer is None or customer.onboarding_status != EM_ANALISE:
        logger.info(
            "%s ignorado: customer %s com status %s",
            ANALYSIS_COMPLETED, event.customer_id,
            customer.onboarding_status if customer else None,
        )
        result = RESULT_IGNORED
    elif _is_stale(customer.business_profile, event.source_event_id):
        logger.info(
            "%s ignorado: customer %s, análise da submissão %s (atual: %s)",
            ANALYSIS_COMPLETED, event.customer_id, event.source_event_id,
            customer.business_profile.submission_event_id,
        )
        result = RESULT_IGNORED
    else:
        profile = customer.business_profile or BusinessProfile(customer_id=customer.id, respostas={})
        profile.analise = {
            "score": event.score,
            "faixa_risco": event.faixa_risco,
            "gerado_por": event.gerado_por,
            "status": event.status,
        }
        customer.onboarding_status = event.status
        db.add(profile)
        result = RESULT_OK

    db.add(ProcessedEvent(event_id=event.event_id, routing_key=ANALYSIS_COMPLETED, result=result))
    db.commit()
    if result == RESULT_OK:
        refresh_manual_queue(db)
    return result
