from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.metrics import ONBOARDING_DRAFTS, ONBOARDING_SUBMISSIONS
from app.core.security import Principal, require_permission
from app.events import ONBOARDING_SUBMITTED, EventPublisher, get_publisher, onboarding_submitted_event
from app.schemas.me import MeOut
from app.schemas.onboarding import OnboardingIn, OnboardingOut
from app.services.onboarding_service import (
    OnboardingConflictError,
    OnboardingService,
    OnboardingValidationError,
    empresa_dict,
    find_by_sub,
    me_view,
    onboarding_view,
)

router = APIRouter(prefix="/me", tags=["portal"])


@router.get("", response_model=MeOut)
def get_me(
    principal: Principal = Depends(require_permission("read:self")),
    db: Session = Depends(get_db),
):
    """Customer vinculado ao `sub` do token (usado também por Score e Transactions via token relay)."""
    return me_view(db, principal.subject)


@router.get("/onboarding", response_model=OnboardingOut)
def get_onboarding(
    principal: Principal = Depends(require_permission("read:self")),
    db: Session = Depends(get_db),
):
    """Rascunho ou envio atual do onboarding PJ do usuário."""
    return onboarding_view(find_by_sub(db, principal.subject))


@router.put(
    "/onboarding",
    response_model=OnboardingOut,
    responses={409: {"description": "Status não editável ou CNPJ de outro cliente"},
               422: {"description": "Envio incompleto: {detail, campos: [{campo, erro}]}"}},
)
def put_onboarding(
    payload: OnboardingIn,
    background: BackgroundTasks,
    principal: Principal = Depends(require_permission("write:self")),
    db: Session = Depends(get_db),
    publisher: EventPublisher = Depends(get_publisher),
):
    """Salva o rascunho (enviar=false) ou envia para análise (enviar=true)."""
    try:
        customer = OnboardingService(db).save(principal.subject, payload)
    except OnboardingConflictError as exc:
        raise HTTPException(409, str(exc))
    except OnboardingValidationError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc), "campos": exc.campos})

    view = onboarding_view(customer)
    if payload.enviar:
        ONBOARDING_SUBMISSIONS.labels(segmento=customer.segmento).inc()
        background.add_task(
            publisher.publish,
            ONBOARDING_SUBMITTED,
            onboarding_submitted_event(
                customer, empresa_dict(customer), view["respostas"], view["observacoes"],
                event_id=customer.business_profile.submission_event_id,
            ),
        )
    else:
        ONBOARDING_DRAFTS.inc()
    return view
