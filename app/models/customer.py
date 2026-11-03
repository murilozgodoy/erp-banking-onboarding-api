from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config.database import Base

TIPO_PF = "PF"
TIPO_PJ = "PJ"


class Customer(Base):
    """Cliente PF (backoffice, POST /customers) ou PJ (portal, vinculado ao `sub` do Auth0).

    Colunas da Fase 2 (auth0_sub..onboarding_status) e o cpf nulo são aplicados em bancos
    existentes por app.config.migrations (create_all não altera tabelas existentes).
    """

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    cpf: Mapped[str | None] = mapped_column(String(14), unique=True, nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(120), nullable=False)
    telefone: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    auth0_sub: Mapped[str | None] = mapped_column(
        String(128), unique=True, nullable=True, index=True
    )
    tipo_pessoa: Mapped[str] = mapped_column(
        String(2), nullable=False, default=TIPO_PF, server_default=TIPO_PF
    )
    cnpj: Mapped[str | None] = mapped_column(String(14), unique=True, nullable=True, index=True)
    razao_social: Mapped[str | None] = mapped_column(String(160), nullable=True)
    nome_fantasia: Mapped[str | None] = mapped_column(String(160), nullable=True)
    segmento: Mapped[str | None] = mapped_column(String(40), nullable=True)
    onboarding_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    address: Mapped["Address | None"] = relationship(
        "Address", back_populates="customer", uselist=False, cascade="all, delete-orphan"
    )
    financial_profile: Mapped["FinancialProfile | None"] = relationship(
        "FinancialProfile", back_populates="customer", uselist=False, cascade="all, delete-orphan"
    )
    anamnesis: Mapped["Anamnesis | None"] = relationship(
        "Anamnesis", back_populates="customer", uselist=False, cascade="all, delete-orphan"
    )
    business_profile: Mapped["BusinessProfile | None"] = relationship(
        "BusinessProfile", back_populates="customer", uselist=False, cascade="all, delete-orphan"
    )
