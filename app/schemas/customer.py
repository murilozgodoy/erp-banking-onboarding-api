from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.address import AddressIn, AddressOut
from app.schemas.anamnesis import AnamnesisOut
from app.schemas.financial_profile import FinancialProfileIn, FinancialProfileOut


class CustomerCreate(BaseModel):
    nome: str = Field(..., min_length=1, max_length=120)
    cpf: str = Field(..., min_length=11, max_length=14)
    email: EmailStr
    telefone: str = Field(..., min_length=8, max_length=20)
    address: AddressIn | None = None
    financial_profile: FinancialProfileIn | None = None


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
