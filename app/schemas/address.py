from pydantic import BaseModel, ConfigDict, Field


class AddressIn(BaseModel):
    rua: str = Field(..., min_length=1, max_length=120)
    numero: str = Field(..., min_length=1, max_length=20)
    cidade: str = Field(..., min_length=1, max_length=80)
    estado: str = Field(..., min_length=2, max_length=2)
    cep: str = Field(..., min_length=8, max_length=10)


class AddressOut(AddressIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
