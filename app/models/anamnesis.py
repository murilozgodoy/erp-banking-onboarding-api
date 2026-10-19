from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config.database import Base
from app.models.customer import Customer


class Anamnesis(Base):
    __tablename__ = "anamnesis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    dividas_ativas: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    comprometimento_renda: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    customer: Mapped[Customer] = relationship("Customer", back_populates="anamnesis")
