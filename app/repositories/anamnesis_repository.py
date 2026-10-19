from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Anamnesis


class AnamnesisRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert(self, customer_id: int, dividas: float, comp_renda: float) -> Anamnesis:
        existing = self.db.execute(
            select(Anamnesis).where(Anamnesis.customer_id == customer_id)
        ).scalar_one_or_none()

        if existing:
            existing.dividas_ativas = dividas
            existing.comprometimento_renda = comp_renda
        else:
            existing = Anamnesis(
                customer_id=customer_id,
                dividas_ativas=dividas,
                comprometimento_renda=comp_renda,
            )
            self.db.add(existing)
        self.db.commit()
        self.db.refresh(existing)
        return existing
