from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AnamnesisIn(BaseModel):
    dividas_ativas: float = Field(..., ge=0)
    comprometimento_renda: float = Field(..., ge=0, le=100)


class AnamnesisOut(AnamnesisIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    updated_at: datetime
