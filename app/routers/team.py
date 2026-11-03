from fastapi import APIRouter, BackgroundTasks, Depends, Path, Response
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.security import Principal, require_permission
from app.events import EventPublisher, get_publisher
from app.events.outbox import publish_pending, session_factory_for
from app.schemas.team import AcceptOut, InviteIn, InviteOut, MemberPatch, TeamMemberOut
from app.team.members import member_view
from app.team.resolver import resolve
from app.team.service import TeamService, invite_url, require_manager, team_member_view

router = APIRouter(prefix="/me/team", tags=["equipe"])

_MANAGER_403 = {403: {"description": 'Sem gerenciar_equipe: {"error":"SEM_PERMISSAO","permissao":"gerenciar_equipe"}; '
                                     'membro suspenso: {"error":"MEMBRO_SUSPENSO"}'}}


def _publish(background: BackgroundTasks, publisher: EventPublisher, db: Session, service: TeamService) -> None:
    """Caminho rápido pós-commit; os eventos já estão no outbox (o relay garante a entrega)."""
    sessions = session_factory_for(db)
    for routing_key, event in service.events:
        background.add_task(publish_pending, publisher, sessions, routing_key, event)


@router.get("", response_model=list[TeamMemberOut], responses=_MANAGER_403)
def list_team(
    principal: Principal = Depends(require_permission("read:self")),
    db: Session = Depends(get_db),
):
    """Membros da empresa (DONO primeiro). Nunca devolve o token, o hash do convite nem o `sub`."""
    actor = require_manager(resolve(db, principal.subject))
    return [team_member_view(m) for m in TeamService(db).list(actor.customer_id)]


@router.post(
    "/invites", status_code=201, response_model=InviteOut,
    responses={**_MANAGER_403, 409: {"description": '{"error":"EMAIL_JA_CADASTRADO"}'}},
)
def create_invite(
    payload: InviteIn,
    background: BackgroundTasks,
    principal: Principal = Depends(require_permission("write:self")),
    db: Session = Depends(get_db),
    publisher: EventPublisher = Depends(get_publisher),
):
    """Convida uma pessoa. O `convite_url` (com o token) só aparece nesta resposta; vale 7 dias."""
    actor = require_manager(resolve(db, principal.subject))
    service = TeamService(db)
    member, token = service.invite(actor, payload)
    _publish(background, publisher, db, service)
    return {"membro": team_member_view(member), "convite_url": invite_url(token)}


@router.patch("/{member_id}", response_model=TeamMemberOut, responses=_MANAGER_403)
def update_member(
    member_id: int,
    payload: MemberPatch,
    background: BackgroundTasks,
    principal: Principal = Depends(require_permission("write:self")),
    db: Session = Depends(get_db),
    publisher: EventPublisher = Depends(get_publisher),
):
    """Edita papel, permissões, limite ou status (ATIVO|SUSPENSO) de outro membro."""
    actor = require_manager(resolve(db, principal.subject))
    service = TeamService(db)
    member = service.update(actor, member_id, payload)
    _publish(background, publisher, db, service)
    return team_member_view(member)


@router.delete("/{member_id}", status_code=204, responses=_MANAGER_403)
def delete_member(
    member_id: int,
    background: BackgroundTasks,
    principal: Principal = Depends(require_permission("write:self")),
    db: Session = Depends(get_db),
    publisher: EventPublisher = Depends(get_publisher),
):
    """Revoga o convite ou remove o membro (nunca o DONO)."""
    actor = require_manager(resolve(db, principal.subject))
    service = TeamService(db)
    service.remove(actor, member_id)
    _publish(background, publisher, db, service)
    return Response(status_code=204)


@router.post(
    "/invites/{token}/accept", response_model=AcceptOut,
    responses={404: {"description": '{"error":"CONVITE_NAO_ENCONTRADO"}'},
               409: {"description": '{"error":"JA_VINCULADO"}'},
               410: {"description": '{"error":"CONVITE_EXPIRADO"}'}},
)
def accept_invite(
    background: BackgroundTasks,
    token: str = Path(min_length=16, max_length=128),
    principal: Principal = Depends(require_permission("read:self")),
    db: Session = Depends(get_db),
    publisher: EventPublisher = Depends(get_publisher),
):
    """Vincula o `sub` do token ao convite (status ATIVO). Idempotente para o mesmo `sub`."""
    service = TeamService(db)
    member = service.accept(principal.subject, token)
    _publish(background, publisher, db, service)
    return {"customer_id": member.customer_id, "membro": member_view(member)}
