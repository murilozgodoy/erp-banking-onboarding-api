from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.security import Principal, require_permission
from app.schemas.me import MeOut
from app.services.onboarding_service import me_view

router = APIRouter(prefix="/me", tags=["portal"])


@router.get("", response_model=MeOut)
def get_me(
    principal: Principal = Depends(require_permission("read:self")),
    db: Session = Depends(get_db),
):
    """Customer vinculado ao `sub` do token (usado também por Score e Transactions via token relay)."""
    return me_view(db, principal.subject)
