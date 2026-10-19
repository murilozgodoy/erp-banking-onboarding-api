from pydantic import BaseModel, ConfigDict, Field


class FinancialProfileIn(BaseModel):
    renda_mensal: float = Field(..., ge=0)
    patrimonio: float = Field(..., ge=0)
    ocupacao: str = Field(..., min_length=1, max_length=60)


class FinancialProfileOut(FinancialProfileIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
