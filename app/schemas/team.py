from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.me import MembroOut
from app.team.permissions import canonical, unknown

# DONO não é convidável nem atribuível (exatamente um DONO por empresa; sem transferência na v1)
PapelConvite = Literal["ADMIN", "FINANCEIRO", "OPERADOR", "LEITURA"]
LIMITE_MAX = 999_999_999_999.99  # NUMERIC(14, 2)


def _check_permissoes(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    invalid = unknown(value)
    if invalid:
        raise ValueError("Permissões desconhecidas: " + ", ".join(invalid))
    return canonical(value)


class InviteIn(BaseModel):
    email: EmailStr = Field(max_length=120)
    nome: str = Field(min_length=1, max_length=160)
    papel: PapelConvite
    permissoes: list[str] | None = None  # None = preset do papel
    limite_pagamento: float | None = Field(default=None, ge=0, le=LIMITE_MAX)

    @field_validator("nome")
    @classmethod
    def _nome(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Nome obrigatório")
        return value

    @field_validator("permissoes")
    @classmethod
    def _permissoes(cls, value):
        return _check_permissoes(value)


class MemberPatch(BaseModel):
    """Campos ausentes não mudam; `limite_pagamento: null` explícito remove o limite.

    `papel: "DONO"` é aceito no schema para responder 403 (quem não é DONO) ou 409 DONO_UNICO.
    """

    papel: Literal["DONO", "ADMIN", "FINANCEIRO", "OPERADOR", "LEITURA"] | None = None
    permissoes: list[str] | None = None
    limite_pagamento: float | None = Field(default=None, ge=0, le=LIMITE_MAX)
    status: Literal["ATIVO", "SUSPENSO"] | None = None

    @field_validator("permissoes")
    @classmethod
    def _permissoes(cls, value):
        return _check_permissoes(value)


class TeamMemberOut(BaseModel):
    """Item de GET /me/team. Nunca inclui o token, o hash do convite nem o `sub`."""

    id: int
    nome: str
    email: str
    papel: str
    permissoes: list[str]
    limite_pagamento: float | None
    status: str
    convite_expira_em: datetime | None
    created_at: datetime
    updated_at: datetime


class InviteOut(BaseModel):
    membro: TeamMemberOut
    convite_url: str


class AcceptOut(BaseModel):
    customer_id: int
    membro: MembroOut
