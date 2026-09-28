from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nome: Mapped[str] = mapped_column(String(120), nullable=False)
    cpf: Mapped[str] = mapped_column(String(14), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(120), nullable=False)
    telefone: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    address: Mapped["Address | None"] = relationship(
        "Address", back_populates="customer", uselist=False, cascade="all, delete-orphan"
    )
    financial_profile: Mapped["FinancialProfile | None"] = relationship(
        "FinancialProfile", back_populates="customer", uselist=False, cascade="all, delete-orphan"
    )
    anamnesis: Mapped["Anamnesis | None"] = relationship(
        "Anamnesis", back_populates="customer", uselist=False, cascade="all, delete-orphan"
    )


class Address(Base):
    __tablename__ = "addresses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    rua: Mapped[str] = mapped_column(String(120), nullable=False)
    numero: Mapped[str] = mapped_column(String(20), nullable=False)
    cidade: Mapped[str] = mapped_column(String(80), nullable=False)
    estado: Mapped[str] = mapped_column(String(2), nullable=False)
    cep: Mapped[str] = mapped_column(String(10), nullable=False)

    customer: Mapped[Customer] = relationship("Customer", back_populates="address")


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
