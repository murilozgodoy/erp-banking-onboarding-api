from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AddressIn(BaseModel):
    rua: str = Field(..., min_length=1, max_length=120)
    numero: str = Field(..., min_length=1, max_length=20)
    cidade: str = Field(..., min_length=1, max_length=80)
    estado: str = Field(..., min_length=2, max_length=2)
    cep: str = Field(..., min_length=8, max_length=10)


class AddressOut(AddressIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class FinancialProfileIn(BaseModel):
    renda_mensal: float = Field(..., ge=0)
    patrimonio: float = Field(..., ge=0)
    ocupacao: str = Field(..., min_length=1, max_length=60)


class FinancialProfileOut(FinancialProfileIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class CustomerCreate(BaseModel):
    nome: str = Field(..., min_length=1, max_length=120)
    cpf: str = Field(..., min_length=11, max_length=14)
    email: EmailStr
    telefone: str = Field(..., min_length=8, max_length=20)
    address: AddressIn | None = None
    financial_profile: FinancialProfileIn | None = None


class AnamnesisIn(BaseModel):
    dividas_ativas: float = Field(..., ge=0)
    comprometimento_renda: float = Field(..., ge=0, le=100)


class AnamnesisOut(AnamnesisIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    updated_at: datetime


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nome: str
    cpf: str
    email: str
    telefone: str
    created_at: datetime
    address: AddressOut | None = None
    financial_profile: FinancialProfileOut | None = None
    anamnesis: AnamnesisOut | None = None
