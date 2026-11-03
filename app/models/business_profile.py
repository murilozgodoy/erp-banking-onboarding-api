from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config.database import Base
from app.models.customer import Customer


class BusinessProfile(Base):
    """Onboarding PJ: dados complementares da empresa, respostas do template e revisão.

    razao_social, nome_fantasia, cnpj, email e telefone ficam em `customers`; os demais campos
    de `empresa` (cidade, estado, fundacao_ano, funcionarios) ficam aqui.
    `analise` guarda o resumo do evento business.analysis_completed
    (score, faixa_risco, gerado_por, status).
    """

    __tablename__ = "business_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    segmento: Mapped[str | None] = mapped_column(String(40), nullable=True)
    cidade: Mapped[str | None] = mapped_column(String(80), nullable=True)
    estado: Mapped[str | None] = mapped_column(String(2), nullable=True)
    fundacao_ano: Mapped[int | None] = mapped_column(Integer, nullable=True)
    funcionarios: Mapped[int | None] = mapped_column(Integer, nullable=True)
    respostas: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    observacoes: Mapped[str | None] = mapped_column(Text, nullable=True)
    analise: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    customer: Mapped[Customer] = relationship("Customer", back_populates="business_profile")
