from datetime import datetime

from app.models import BusinessProfile, Customer


def make_pj(db, sub="auth0|pj", status="EM_ANALISE", cnpj="11222333000181", **profile):
    customer = Customer(
        nome="Padaria Boa LTDA", email="contato@padaria.com", telefone="11988887777",
        auth0_sub=sub, tipo_pessoa="PJ", cnpj=cnpj, razao_social="Padaria Boa LTDA",
        nome_fantasia="Padaria Boa", segmento="alimentacao", onboarding_status=status,
    )
    customer.business_profile = BusinessProfile(
        segmento="alimentacao", cidade="São Paulo", estado="SP", fundacao_ano=2015,
        funcionarios=12, respostas={"faturamento_mensal": 80000}, observacoes="Padaria de bairro",
        submitted_at=profile.pop("submitted_at", datetime(2026, 11, 1, 12, 0)), **profile,
    )
    db.add(customer)
    db.commit()
    return customer
