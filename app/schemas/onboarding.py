from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.me import EmpresaOut
from app.templates import SEGMENTOS

UFS = frozenset(
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
)

_CNPJ_W1 = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_CNPJ_W2 = (6, *_CNPJ_W1)


def _cnpj_digit(digits: str, weights: tuple[int, ...]) -> int:
    rest = sum(int(d) * w for d, w in zip(digits, weights)) % 11
    return 0 if rest < 2 else 11 - rest


def normalize_cnpj(value: str) -> str:
    """Remove a máscara e valida os dígitos verificadores; ValueError se inválido."""
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) != 14 or len(set(digits)) == 1:
        raise ValueError("CNPJ deve ter 14 dígitos")
    if (
        _cnpj_digit(digits[:12], _CNPJ_W1) != int(digits[12])
        or _cnpj_digit(digits[:13], _CNPJ_W2) != int(digits[13])
    ):
        raise ValueError("CNPJ com dígito verificador inválido")
    return digits


class EmpresaIn(BaseModel):
    """Todos os campos são opcionais no rascunho; o envio exige os obrigatórios (ver service)."""

    razao_social: str | None = Field(default=None, max_length=160)
    nome_fantasia: str | None = Field(default=None, max_length=160)
    cnpj: str | None = None
    email: EmailStr | None = Field(default=None, max_length=120)
    telefone: str | None = Field(default=None, min_length=8, max_length=20)
    cidade: str | None = Field(default=None, max_length=80)
    estado: str | None = None
    fundacao_ano: int | None = Field(default=None, ge=1800, le=2100)
    funcionarios: int | None = Field(default=None, ge=0)

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_none(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("cnpj")
    @classmethod
    def _cnpj(cls, value: str | None) -> str | None:
        return normalize_cnpj(value) if value is not None else None

    @field_validator("estado")
    @classmethod
    def _uf(cls, value: str | None) -> str | None:
        if value is None:
            return None
        uf = value.upper()
        if uf not in UFS:
            raise ValueError("UF inválida")
        return uf

    @field_validator("fundacao_ano")
    @classmethod
    def _ano(cls, value: int | None) -> int | None:
        if value is not None and value > datetime.now().year:
            raise ValueError("Ano de fundação no futuro")
        return value


class OnboardingIn(BaseModel):
    empresa: EmpresaIn = Field(default_factory=EmpresaIn)
    segmento: str | None = None
    respostas: dict = Field(default_factory=dict)
    observacoes: str | None = Field(default=None, max_length=5000)
    enviar: bool = False

    @field_validator("segmento")
    @classmethod
    def _segmento(cls, value: str | None) -> str | None:
        if value is not None and value not in SEGMENTOS:
            raise ValueError("Segmento desconhecido; use um de: " + ", ".join(SEGMENTOS))
        return value


class OnboardingOut(BaseModel):
    empresa: EmpresaOut | None
    segmento: str | None
    respostas: dict
    observacoes: str | None
    onboarding_status: str
    updated_at: datetime | None
