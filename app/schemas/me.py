from pydantic import BaseModel


class EmpresaOut(BaseModel):
    razao_social: str | None = None
    nome_fantasia: str | None = None
    cnpj: str | None = None
    email: str | None = None
    telefone: str | None = None
    cidade: str | None = None
    estado: str | None = None
    fundacao_ano: int | None = None
    funcionarios: int | None = None


class MeOut(BaseModel):
    customer_id: int | None
    onboarding_status: str
    empresa: EmpresaOut | None
