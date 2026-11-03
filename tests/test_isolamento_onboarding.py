"""Revisão de segurança: isolamento entre empresas (IDOR), papéis da equipe, convite e entradas."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.models import CompanyMember, Customer
from app.team.members import ensure_owner_member
from app.team.service import hash_token
from tests.factories import make_pj
from tests.test_onboarding import _body
from tests.test_team_routes import DONO_SUB, _as, _invite, _member, _token, company  # noqa: F401

CLIENTE = ("read:self", "write:self")
DONO_B = "auth0|dono-b"
CNPJ_B = "11444777000161"


@pytest.fixture()
def company_b(db_session):
    customer = make_pj(db_session, sub=DONO_B, cnpj=CNPJ_B, status="APROVADO")
    dono = ensure_owner_member(db_session, customer)
    member = _member(db_session, customer.id, "auth0|fin-b", email="fin@b.com")
    return customer.id, dono.id, member.id


def _snapshot(db, member_id):
    db.expire_all()
    m = db.get(CompanyMember, member_id)
    return (m.papel, list(m.permissoes or []), m.limite_pagamento, m.status, m.auth0_sub, m.updated_at)


# ---------- /me/team/{id} de outra empresa ----------

def test_team_ids_from_another_company_are_404_and_unchanged(client, db_session, company, company_b):
    _, b_dono, b_fin = company_b
    before = {i: _snapshot(db_session, i) for i in (b_dono, b_fin)}
    _as(DONO_SUB)
    for target in (b_fin, b_dono, 999_999):
        for response in (
            client.patch(f"/me/team/{target}", json={"status": "SUSPENSO"}),
            client.patch(f"/me/team/{target}", json={"papel": "LEITURA", "permissoes": []}),
            client.delete(f"/me/team/{target}"),
        ):
            # o mesmo 404 para DONO de outra empresa e id inexistente: não revela se o id existe
            assert response.status_code == 404 and response.json() == {"error": "MEMBRO_NAO_ENCONTRADO"}
        assert client.get(f"/me/team/{target}").status_code == 405  # não há GET por id
    assert {i: _snapshot(db_session, i) for i in (b_dono, b_fin)} == before
    assert [m["id"] for m in client.get("/me/team").json()] == [company[1]]  # só a própria equipe


# ---------- aceite do convite ----------

def test_accept_invite_of_other_company_when_already_linked_is_409(client, db_session, company, company_b):
    _member(db_session, company[0], "auth0|fin-a")
    _as(DONO_B)
    token = _token(_invite(client, email="novo@b.com"))
    for sub in ("auth0|fin-a", DONO_SUB, "auth0|fin-b"):  # membro de A, dono de A, membro de B
        _as(sub)
        response = client.post(f"/me/team/invites/{token}/accept")
        assert response.status_code == 409 and response.json() == {"error": "JA_VINCULADO"}
    invited = db_session.scalar(select(CompanyMember).where(CompanyMember.email == "novo@b.com"))
    assert invited.status == "CONVIDADO" and invited.auth0_sub is None


def test_accept_expired_reused_revoked_and_invalid(client, db_session, company):
    _as(DONO_SUB)
    token = _token(_invite(client, email="a@x.com"))
    db_session.execute(update(CompanyMember).where(CompanyMember.email == "a@x.com")
                       .values(invite_expires_at=datetime.utcnow() - timedelta(seconds=1)))
    db_session.commit()
    _as("auth0|novo")
    expired = client.post(f"/me/team/invites/{token}/accept")
    assert expired.status_code == 410 and expired.json() == {"error": "CONVITE_EXPIRADO"}

    _as(DONO_SUB)
    token = _token(_invite(client, email="b@x.com"))
    _as("auth0|x")
    assert client.post(f"/me/team/invites/{token}/accept").status_code == 200
    _as("auth0|y")  # token já usado por outra pessoa
    reused = client.post(f"/me/team/invites/{token}/accept")
    assert reused.status_code == 404 and reused.json() == {"error": "CONVITE_NAO_ENCONTRADO"}
    _as("auth0|x")  # o mesmo sub: idempotente, mesmo vínculo
    assert client.post(f"/me/team/invites/{token}/accept").json()["customer_id"] == company[0]

    _as(DONO_SUB)
    revoked = _invite(client, email="c@x.com")
    client.delete(f"/me/team/{revoked.json()['membro']['id']}")
    _as("auth0|z")
    for bad in (_token(revoked), "x" * 43, "A" * 128):
        response = client.post(f"/me/team/invites/{bad}/accept")
        assert response.status_code == 404 and response.json() == {"error": "CONVITE_NAO_ENCONTRADO"}
    assert client.post("/me/team/invites/curto/accept").status_code == 422
    assert client.post(f"/me/team/invites/{'A' * 129}/accept").status_code == 422


def test_invite_token_stored_only_as_hash_and_never_listed(client, db_session, company):
    _as(DONO_SUB)
    response = _invite(client)
    token = _token(response)
    member = db_session.scalar(select(CompanyMember).where(CompanyMember.email == "maria@empresa.com"))
    assert member.invite_token_hash == hash_token(token) != token
    columns = {c.key: getattr(member, c.key) for c in CompanyMember.__table__.columns}
    assert not any(token in str(v) for v in columns.values())
    listed = client.get("/me/team").text
    assert token not in listed and member.invite_token_hash not in listed
    assert "auth0|" not in listed  # nem o sub


# ---------- /me e /me/onboarding ----------

def test_me_and_onboarding_return_only_callers_company(client, db_session, company, company_b):
    a_id, b_id = company[0], company_b[0]
    expected = {DONO_SUB: a_id, DONO_B: b_id, "auth0|fin-b": b_id}
    for sub, customer_id in expected.items():
        _as(sub)
        assert client.get("/me").json()["customer_id"] == customer_id
        cnpj = client.get("/me/onboarding").json()["empresa"]["cnpj"]
        assert cnpj == db_session.get(Customer, customer_id).cnpj
    _as("auth0|ninguem")
    assert client.get("/me").json()["customer_id"] is None
    assert client.get("/me/onboarding").json()["empresa"] is None


def test_put_onboarding_cannot_take_other_company_cnpj(client, db_session, company_b):
    _as("auth0|novo")
    body = _body()
    body["empresa"]["cnpj"] = CNPJ_B
    response = client.put("/me/onboarding", json=body)
    assert response.status_code == 409
    assert CNPJ_B not in response.text  # mensagem com só o final do CNPJ
    db_session.expire_all()
    assert db_session.get(Customer, company_b[0]).auth0_sub == DONO_B


# ---------- rotas de staff com token de cliente ----------

def test_staff_routes_reject_client_token(client, db_session):
    customer = make_pj(db_session, sub="auth0|c", status="ANALISE_MANUAL")
    _as("auth0|c", CLIENTE)
    assert client.get("/onboarding/reviews").status_code == 403
    assert client.get("/onboarding/reviews?status=APROVADO").status_code == 403
    response = client.post(f"/onboarding/reviews/{customer.id}/decision", json={"decisao": "APROVADO"})
    assert response.status_code == 403
    assert client.get("/customers").status_code == 403
    assert client.get(f"/customers/{customer.id}").status_code == 403
    db_session.expire_all()
    assert db_session.get(Customer, customer.id).onboarding_status == "ANALISE_MANUAL"


# ---------- membro suspenso, sem gerenciar_equipe, sem read:self ----------

def test_suspended_member_is_403_on_all_me_routes(client, db_session, company):
    _member(db_session, company[0], "auth0|sus", papel="ADMIN", status="SUSPENSO")
    _as("auth0|sus")
    for response in (
        client.get("/me"),
        client.get("/me/onboarding"),
        client.put("/me/onboarding", json=_body()),
        client.get("/me/team"),
        _invite(client),
        client.patch(f"/me/team/{company[1]}", json={"limite_pagamento": 1}),
        client.delete(f"/me/team/{company[1]}"),
    ):
        assert response.status_code == 403 and response.json() == {"error": "MEMBRO_SUSPENSO"}


def test_member_without_gerenciar_equipe_is_403(client, db_session, company):
    other = _member(db_session, company[0], "auth0|op", papel="OPERADOR")
    _member(db_session, company[0], "auth0|fin")
    before = _snapshot(db_session, other.id)
    _as("auth0|fin")
    denied = {"error": "SEM_PERMISSAO", "permissao": "gerenciar_equipe"}
    for response in (
        client.get("/me/team"),
        _invite(client),
        client.patch(f"/me/team/{other.id}", json={"status": "SUSPENSO"}),
        client.delete(f"/me/team/{other.id}"),
    ):
        assert response.status_code == 403 and response.json() == denied
    assert _snapshot(db_session, other.id) == before


@pytest.mark.parametrize("path", ["/me", "/me/onboarding", "/me/team"])
def test_token_without_read_self_is_403(client, company, path):
    _as(DONO_SUB, {"write:self", "read:customers"})
    assert client.get(path).status_code == 403


# ---------- DONO protegido e escalada de privilégio ----------

def test_nobody_demotes_suspends_or_removes_the_dono(client, db_session, company):
    _member(db_session, company[0], "auth0|adm", papel="ADMIN")
    before = _snapshot(db_session, company[1])
    _as("auth0|adm")
    for response in (
        client.patch(f"/me/team/{company[1]}", json={"papel": "LEITURA"}),
        client.patch(f"/me/team/{company[1]}", json={"permissoes": []}),
        client.patch(f"/me/team/{company[1]}", json={"status": "SUSPENSO"}),
        client.patch(f"/me/team/{company[1]}", json={"limite_pagamento": 0}),
        client.delete(f"/me/team/{company[1]}"),
    ):
        assert response.status_code == 403 and response.json() == {"error": "DONO_PROTEGIDO"}
    assert _snapshot(db_session, company[1]) == before


def test_admin_cannot_escalate(client, db_session, company):
    adm = _member(db_session, company[0], "auth0|adm", papel="ADMIN")
    fin = _member(db_session, company[0], "auth0|fin")
    snapshots = {i: _snapshot(db_session, i) for i in (adm.id, fin.id)}
    _as("auth0|adm")
    for patch in ({"papel": "DONO"}, {"permissoes": ["gerenciar_equipe"]}, {"limite_pagamento": None}):
        response = client.patch(f"/me/team/{adm.id}", json=patch)  # a si mesmo
        assert response.status_code == 403 and response.json() == {"error": "AUTO_EDICAO"}
    response = client.patch(f"/me/team/{fin.id}", json={"papel": "DONO"})
    assert response.status_code == 403 and response.json() == {"error": "SEM_PERMISSAO", "permissao": "dono"}
    assert _invite(client, papel="DONO").status_code == 422
    assert {i: _snapshot(db_session, i) for i in (adm.id, fin.id)} == snapshots

    _as(DONO_SUB)  # nem o DONO cria um segundo DONO
    assert client.patch(f"/me/team/{fin.id}", json={"papel": "DONO"}).json() == {"error": "DONO_UNICO"}


def test_limited_manager_cannot_grant_what_he_lacks(client, db_session, company):
    _member(db_session, company[0], "auth0|ger", papel="LEITURA", permissoes=["ver_financeiro", "gerenciar_equipe"])
    fin = _member(db_session, company[0], "auth0|fin")
    before = _snapshot(db_session, fin.id)
    _as("auth0|ger")
    for response in (
        client.patch(f"/me/team/{fin.id}", json={"papel": "ADMIN"}),  # preset do ADMIN tem tudo
        client.patch(f"/me/team/{fin.id}", json={"permissoes": ["contratar_credito"]}),
        _invite(client, papel="ADMIN"),
        _invite(client, papel="LEITURA", permissoes=["pagar"]),
    ):
        assert response.status_code == 403 and response.json()["error"] == "SEM_PERMISSAO"
    assert _snapshot(db_session, fin.id) == before


# ---------- entradas ----------

@pytest.mark.parametrize("raw", ["-1", "-0.01", "NaN", "Infinity", "-Infinity", "1e13", "1e400"])
def test_limite_pagamento_invalid_is_422(client, db_session, company, raw):
    fin = _member(db_session, company[0], "auth0|fin")
    _as(DONO_SUB)
    headers = {"Content-Type": "application/json"}
    invite = ('{"email": "z@x.com", "nome": "Z", "papel": "LEITURA", "limite_pagamento": %s}' % raw)
    assert client.post("/me/team/invites", content=invite, headers=headers).status_code == 422
    patch = '{"limite_pagamento": %s}' % raw
    assert client.patch(f"/me/team/{fin.id}", content=patch, headers=headers).status_code == 422
    assert db_session.scalar(select(CompanyMember).where(CompanyMember.email == "z@x.com")) is None


@pytest.mark.parametrize("email", ["nao-e-email", "a@", "@x.com", "a b@x.com", "a" * 120 + "@x.com"])
def test_invite_invalid_email_is_422(client, company, email):
    _as(DONO_SUB)
    assert _invite(client, email=email).status_code == 422


@pytest.mark.parametrize("cnpj", ["11.222.333/0001-80", "11111111111111", "1122233300018", "１１２２２３３３０００１８１",
                                  "11222333000181a"])
def test_invalid_cnpj_is_422(client, cnpj):
    body = _body()
    body["empresa"]["cnpj"] = cnpj
    assert client.put("/me/onboarding", json=body).status_code == 422

