from app.core.security import Principal, require_auth
from app.main import app
from app.models import BusinessProfile, Customer


def _as(permissions, subject="auth0|test"):
    app.dependency_overrides[require_auth] = lambda: Principal(
        token="t", subject=subject, permissions=frozenset(permissions)
    )


def test_me_without_customer(client):
    response = client.get("/me")
    assert response.status_code == 200
    assert response.json() == {
        "customer_id": None, "onboarding_status": "NAO_INICIADO", "empresa": None, "membro": None,
    }


def test_me_requires_read_self(client):
    _as({"read:customers"})
    assert client.get("/me").status_code == 403


def test_me_with_pj_customer(client, db_session):
    customer = Customer(
        nome="Padaria Boa LTDA", email="contato@padaria.com", telefone="11988887777",
        auth0_sub="auth0|test", tipo_pessoa="PJ", cnpj="11222333000181",
        razao_social="Padaria Boa LTDA", nome_fantasia="Padaria Boa",
        segmento="alimentacao", onboarding_status="EM_ANALISE",
    )
    customer.business_profile = BusinessProfile(
        segmento="alimentacao", cidade="São Paulo", estado="SP", fundacao_ano=2015,
        funcionarios=12, respostas={},
    )
    db_session.add(customer)
    # outro cliente (PF do backoffice) não interfere
    db_session.add(Customer(nome="Ana", cpf="12345678900", email="a@x.com", telefone="11999990000"))
    db_session.commit()

    body = client.get("/me").json()
    assert body == {
        "customer_id": customer.id,
        "onboarding_status": "EM_ANALISE",
        "empresa": {
            "razao_social": "Padaria Boa LTDA", "nome_fantasia": "Padaria Boa",
            "cnpj": "11222333000181", "email": "contato@padaria.com", "telefone": "11988887777",
            "cidade": "São Paulo", "estado": "SP", "fundacao_ano": 2015, "funcionarios": 12,
        },
        "membro": {
            "id": body["membro"]["id"], "nome": "Padaria Boa LTDA", "email": "contato@padaria.com",
            "papel": "DONO", "permissoes": [
                "ver_financeiro", "pagar", "aprovar_pagamentos", "pedir_credito", "contratar_credito",
                "gerenciar_estoque", "gerenciar_equipe", "usar_assistente",
            ],
            "limite_pagamento": None, "status": "ATIVO",
        },
    }


def test_me_draft_without_profile_and_blank_contact(client, db_session):
    db_session.add(Customer(nome="", email="", telefone="", auth0_sub="auth0|test", tipo_pessoa="PJ"))
    db_session.commit()
    body = client.get("/me").json()
    assert body["onboarding_status"] == "NAO_INICIADO"
    assert body["empresa"] == {k: None for k in (
        "razao_social", "nome_fantasia", "cnpj", "email", "telefone",
        "cidade", "estado", "fundacao_ano", "funcionarios")}


def test_customers_list_with_pj_without_cpf(client, db_session, sample_customer_payload):
    assert client.post("/customers", json=sample_customer_payload).status_code == 201
    db_session.add(Customer(nome="Empresa X", email="x@x.com", telefone="1133334444",
                            tipo_pessoa="PJ", cnpj="11222333000181", razao_social="Empresa X"))
    db_session.commit()
    items = client.get("/customers").json()
    assert items[0]["cpf"] is None and items[0]["tipo_pessoa"] == "PJ"
    assert items[1]["cpf"] == "12345678900" and items[1]["tipo_pessoa"] == "PF"
