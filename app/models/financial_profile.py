from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config.database import Base
from app.models.customer import Customer


class FinancialProfile(Base):
    __tablename__ = "financial_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    renda_mensal: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    patrimonio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ocupacao: Mapped[str] = mapped_column(String(60), nullable=False, default="")

    customer: Mapped[Customer] = relationship("Customer", back_populates="financial_profile")
