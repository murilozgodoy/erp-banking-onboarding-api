from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.metrics import ONBOARDING_DRAFTS, ONBOARDING_SUBMISSIONS
from app.core.security import Principal, require_permission
from app.events import EventPublisher, get_publisher
from app.events.outbox import publish_pending, session_factory_for
from app.schemas.me import MeOut
from app.schemas.onboarding import OnboardingIn, OnboardingOut
from app.services.onboarding_service import (
    OnboardingConflictError,
    OnboardingService,
    OnboardingValidationError,
    onboarding_view,
)
from app.team.resolver import me_view, require_owner, resolve

router = APIRouter(prefix="/me", tags=["portal"])


@router.get("", response_model=MeOut)
def get_me(
    principal: Principal = Depends(require_permission("read:self")),
    db: Session = Depends(get_db),
):
    """Empresa e membro do `sub` do token (usado também por Score e Transactions via token relay).

    O `sub` pode ser do dono (`customers.auth0_sub`) ou de um membro ATIVO da equipe; membro suspenso → 403
    `{"error":"MEMBRO_SUSPENSO"}`.
    """
    return me_view(db, principal.subject)


@router.get("/onboarding", response_model=OnboardingOut)
def get_onboarding(
    principal: Principal = Depends(require_permission("read:self")),
    db: Session = Depends(get_db),
):
    """Rascunho ou envio atual do onboarding PJ da empresa do usuário (dono ou membro, leitura)."""
    return onboarding_view(resolve(db, principal.subject).customer)


@router.put(
    "/onboarding",
    response_model=OnboardingOut,
    responses={403: {"description": 'Membro que não é DONO: {"error":"SEM_PERMISSAO","permissao":"dono"}'},
               409: {"description": "Status não editável ou CNPJ de outro cliente"},
               422: {"description": "Envio incompleto: {detail, campos: [{campo, erro}]}"}},
)
def put_onboarding(
    payload: OnboardingIn,
    background: BackgroundTasks,
    principal: Principal = Depends(require_permission("write:self")),
    db: Session = Depends(get_db),
    publisher: EventPublisher = Depends(get_publisher),
):
    """Salva o rascunho (enviar=false) ou envia para análise (enviar=true). Só o DONO (ou quem ainda não tem
    empresa, que vira o DONO) pode alterar."""
    membership = resolve(db, principal.subject)
    require_owner(membership)
    service = OnboardingService(db)
    try:
        customer = service.save(principal.subject, payload, customer=membership.customer)
    except OnboardingConflictError as exc:
        raise HTTPException(409, str(exc))
    except OnboardingValidationError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc), "campos": exc.campos})

    view = onboarding_view(customer)
    if payload.enviar:
        ONBOARDING_SUBMISSIONS.labels(segmento=customer.segmento).inc()
        # já está no outbox (mesmo commit); aqui é só o caminho rápido
        sessions = session_factory_for(db)
        for routing_key, event in service.events:
            background.add_task(publish_pending, publisher, sessions, routing_key, event)
    else:
        ONBOARDING_DRAFTS.inc()
    return view
