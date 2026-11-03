"""Equipe (PR 2): rotas /me/team, convite, aceite, evento company.member_changed e métrica."""
import hashlib
from datetime import datetime, timedelta

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import sessionmaker

from app.config.database import Base
from app.config.settings import settings
from app.core.errors import ApiError
from app.core.security import Principal, require_auth
from app.main import _init_team_gauge, app
from app.models import CompanyMember, OutboxEvent
from app.schemas.team import MemberPatch
from app.team import service as service_module
from app.team.members import ensure_owner_member, refresh_team_members
from app.team.permissions import PERMISSOES, preset
from app.team.service import TeamService, hash_token
from tests.factories import make_pj

ALL = list(PERMISSOES)
DONO_SUB = "auth0|dono"
TEAM_KEYS = {"id", "nome", "email", "papel", "permissoes", "limite_pagamento", "status",
             "convite_expira_em", "created_at", "updated_at"}


def _as(subject, permissions=("read:self", "write:self")):
    app.dependency_overrides[require_auth] = lambda: Principal(
        token="t", subject=subject, permissions=frozenset(permissions)
    )


def _gauge(papel, status):
    return REGISTRY.get_sample_value("team_members_total", {"papel": papel, "status": status})


def _member(db, customer_id, sub, papel="FINANCEIRO", status="ATIVO", email=None, **kw):
    member = CompanyMember(
        customer_id=customer_id, auth0_sub=sub, email=email or f"{sub.split('|')[-1]}@x.com",
        nome=kw.pop("nome", "Fulano"), papel=papel, permissoes=kw.pop("permissoes", preset(papel)),
        status=status, created_by=DONO_SUB, **kw,
    )
    db.add(member)
    db.commit()
    return member


def _events(db):
    db.expire_all()
    return [e.payload for e in db.scalars(
        select(OutboxEvent).where(OutboxEvent.routing_key == "company.member_changed").order_by(OutboxEvent.id)
    )]


@pytest.fixture()
def company(db_session):
    customer = make_pj(db_session, sub=DONO_SUB, status="APROVADO")
    dono = ensure_owner_member(db_session, customer)
    return customer.id, dono.id


def _invite(client, **changes):
    body = {"email": "Maria@Empresa.com", "nome": "Maria", "papel": "FINANCEIRO"}
    body.update(changes)
    return client.post("/me/team/invites", json=body)


def _token(response):
    return response.json()["convite_url"].rsplit("/", 1)[-1]


# ---------- permissão gerenciar_equipe ----------

def test_routes_require_gerenciar_equipe(client, db_session, company):
    customer_id, dono_id = company
    _member(db_session, customer_id, "auth0|fin")
    _as("auth0|fin")
    denied = {"error": "SEM_PERMISSAO", "permissao": "gerenciar_equipe"}
    for response in (
        client.get("/me/team"),
        _invite(client),
        client.patch(f"/me/team/{dono_id}", json={"limite_pagamento": 1}),
        client.delete(f"/me/team/{dono_id}"),
    ):
        assert response.status_code == 403 and response.json() == denied
    _as("auth0|sem-empresa")
    assert client.get("/me/team").json() == denied


def test_suspended_manager_gets_membro_suspenso(client, db_session, company):
    _member(db_session, company[0], "auth0|adm", papel="ADMIN", status="SUSPENSO")
    _as("auth0|adm")
    response = client.get("/me/team")
    assert response.status_code == 403 and response.json() == {"error": "MEMBRO_SUSPENSO"}


def test_auth0_permissions_still_apply(client, company):
    _as(DONO_SUB, {"read:self"})
    assert client.get("/me/team").status_code == 200
    assert _invite(client).status_code == 403  # escrita exige write:self


# ---------- GET /me/team ----------

def test_list_team_shape(client, db_session, company):
    customer_id, dono_id = company
    _member(db_session, customer_id, "auth0|op", papel="OPERADOR", limite_pagamento=250)
    other = make_pj(db_session, sub="auth0|outra", cnpj="11444777000161")
    _member(db_session, other.id, "auth0|alheio")
    _as(DONO_SUB)
    body = client.get("/me/team").json()
    assert [m["papel"] for m in body] == ["DONO", "OPERADOR"]  # só a empresa do sub, DONO primeiro
    assert all(set(m) == TEAM_KEYS for m in body)
    assert body[0]["id"] == dono_id and body[0]["permissoes"] == ALL
    assert body[1]["limite_pagamento"] == 250.0 and body[1]["convite_expira_em"] is None


# ---------- POST /me/team/invites ----------

def test_invite_creates_member_with_hashed_token(client, db_session, company):
    customer_id, _ = company
    _as(DONO_SUB)
    response = _invite(client, limite_pagamento=1000)
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"membro", "convite_url"}
    assert body["convite_url"].startswith("https://erp-banking-front.vercel.app/convite/")
    token = _token(response)
    assert len(token) >= 43
    membro = body["membro"]
    assert set(membro) == TEAM_KEYS
    assert membro["email"] == "maria@empresa.com" and membro["status"] == "CONVIDADO"
    assert membro["permissoes"] == preset("FINANCEIRO") and membro["limite_pagamento"] == 1000.0

    row = db_session.get(CompanyMember, membro["id"])
    assert row.invite_token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert row.auth0_sub is None and row.created_by == DONO_SUB and row.customer_id == customer_id
    assert timedelta(days=6, hours=23) < row.invite_expires_at - datetime.utcnow() <= timedelta(days=7)
    # o token nunca volta depois da criação
    assert token not in client.get("/me/team").text
    assert token not in client.patch(f"/me/team/{row.id}", json={"papel": "LEITURA"}).text


def test_invite_uses_front_url_setting(client, company, monkeypatch):
    monkeypatch.setattr(settings, "front_url", "https://portal.test/")
    _as(DONO_SUB)
    assert _invite(client).json()["convite_url"].startswith("https://portal.test/convite/")


def test_invite_with_custom_permissions(client, company):
    _as(DONO_SUB)
    body = _invite(client, papel="OPERADOR", permissoes=["usar_assistente", "pagar", "pagar"]).json()
    assert body["membro"]["permissoes"] == ["pagar", "usar_assistente"]


@pytest.mark.parametrize("changes", [
    {"papel": "DONO"},
    {"papel": "CHEFE"},
    {"permissoes": ["pagar", "voar"]},
    {"limite_pagamento": -1},
    {"email": "nao-e-email"},
    {"nome": "   "},
])
def test_invite_validation(client, company, changes):
    _as(DONO_SUB)
    assert _invite(client, **changes).status_code == 422


def test_invite_duplicate_email_is_409(client, db_session, company):
    _as(DONO_SUB)
    assert _invite(client).status_code == 201
    duplicate = _invite(client, email="MARIA@empresa.com")
    assert duplicate.status_code == 409 and duplicate.json() == {"error": "EMAIL_JA_CADASTRADO"}
    # o e-mail do DONO também conta
    assert _invite(client, email="contato@padaria.com").status_code == 409
    # mesmo e-mail em outra empresa é permitido
    make_pj(db_session, sub="auth0|outra", cnpj="11444777000161")
    _as("auth0|outra")
    assert _invite(client).status_code == 201


def test_invite_race_on_unique_index_is_409(db_session, company, monkeypatch):
    customer_id, dono_id = company
    _member(db_session, customer_id, "auth0|maria", email="maria@empresa.com")
    real_scalar = db_session.scalar
    calls = {"n": 0}

    def scalar_missing_duplicate(statement, *args, **kwargs):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_scalar(statement, *args, **kwargs)

    from app.schemas.team import InviteIn

    monkeypatch.setattr(db_session, "scalar", scalar_missing_duplicate)
    service = TeamService(db_session)
    with pytest.raises(ApiError) as exc:
        service.invite(db_session.get(CompanyMember, dono_id),
                       InviteIn(email="maria@empresa.com", nome="Maria", papel="LEITURA"))
    assert exc.value.status_code == 409 and service.events == []


def test_manager_cannot_grant_permissions_he_lacks(client, db_session, company):
    customer_id, _ = company
    _member(db_session, customer_id, "auth0|rh", papel="LEITURA",
            permissoes=["ver_financeiro", "gerenciar_equipe"])
    alvo = _member(db_session, customer_id, "auth0|alvo", papel="LEITURA")
    _as("auth0|rh")
    denied = _invite(client, papel="FINANCEIRO")
    assert denied.status_code == 403 and denied.json() == {"error": "SEM_PERMISSAO", "permissao": "pagar"}
    assert _invite(client, papel="LEITURA").status_code == 201
    patch = client.patch(f"/me/team/{alvo.id}", json={"permissoes": ["ver_financeiro", "pedir_credito"]})
    assert patch.json() == {"error": "SEM_PERMISSAO", "permissao": "pedir_credito"}


# ---------- POST /me/team/invites/{token}/accept ----------

def test_accept_binds_sub_and_is_idempotent(client, db_session, company):
    customer_id, _ = company
    _as(DONO_SUB)
    created = _invite(client, papel="OPERADOR", limite_pagamento=500)
    token, member_id = _token(created), created.json()["membro"]["id"]

    _as("auth0|maria", {"read:self"})  # aceite só exige read:self
    first = client.post(f"/me/team/invites/{token}/accept")
    assert first.status_code == 200
    assert first.json() == {
        "customer_id": customer_id,
        "membro": {"id": member_id, "nome": "Maria", "email": "maria@empresa.com", "papel": "OPERADOR",
                   "permissoes": preset("OPERADOR"), "limite_pagamento": 500.0, "status": "ATIVO"},
    }
    assert token not in first.text
    row = db_session.get(CompanyMember, member_id)
    db_session.refresh(row)
    assert (row.auth0_sub, row.status, row.invite_token_hash, row.invite_expires_at) == (
        "auth0|maria", "ATIVO", None, None)

    again = client.post(f"/me/team/invites/{token}/accept")
    assert again.status_code == 200 and again.json() == first.json()
    me = client.get("/me").json()
    assert me["customer_id"] == customer_id and me["membro"]["id"] == member_id

    _as("auth0|intruso", {"read:self"})
    assert client.post(f"/me/team/invites/{token}/accept").json() == {"error": "CONVITE_NAO_ENCONTRADO"}
    assert [e["acao"] for e in _events(db_session)] == ["CONVIDADO", "ACEITO"]


def test_accept_unknown_and_expired(client, db_session, company):
    _as("auth0|maria", {"read:self"})
    unknown = client.post("/me/team/invites/" + "x" * 43 + "/accept")
    assert unknown.status_code == 404 and unknown.json() == {"error": "CONVITE_NAO_ENCONTRADO"}

    _as(DONO_SUB)
    created = _invite(client)
    db_session.execute(update(CompanyMember).where(CompanyMember.id == created.json()["membro"]["id"])
                       .values(invite_expires_at=datetime.utcnow() - timedelta(seconds=1)))
    db_session.commit()
    _as("auth0|maria", {"read:self"})
    expired = client.post(f"/me/team/invites/{_token(created)}/accept")
    assert expired.status_code == 410 and expired.json() == {"error": "CONVITE_EXPIRADO"}


def test_accept_rejects_sub_already_linked(client, db_session, company):
    customer_id, _ = company
    other = make_pj(db_session, sub="auth0|outra", cnpj="11444777000161")
    _member(db_session, other.id, "auth0|func-outra")
    _as(DONO_SUB)
    token = _token(_invite(client))
    for sub in ("auth0|outra", "auth0|func-outra", DONO_SUB):  # dono de empresa, membro de outra, o próprio dono
        _as(sub, {"read:self"})
        response = client.post(f"/me/team/invites/{token}/accept")
        assert response.status_code == 409 and response.json() == {"error": "JA_VINCULADO"}


def test_accept_by_suspended_member_with_unknown_token(client, db_session, company):
    _member(db_session, company[0], "auth0|susp", status="SUSPENSO")
    _as("auth0|susp", {"read:self"})
    assert client.post("/me/team/invites/" + "y" * 43 + "/accept").json() == {"error": "MEMBRO_SUSPENSO"}


def _file_db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'team.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False)


def test_accept_concurrent_same_sub_is_idempotent(tmp_path, monkeypatch):
    engine, Session = _file_db(tmp_path)
    with Session() as db:
        customer = make_pj(db, sub=DONO_SUB)
        token = "t" * 43
        invite = _member(db, customer.id, "auth0|tmp", status="CONVIDADO", email="m@x.com",
                         invite_token_hash=hash_token(token),
                         invite_expires_at=datetime.utcnow() + timedelta(days=1))
        db.execute(update(CompanyMember).where(CompanyMember.id == invite.id).values(auth0_sub=None))
        db.commit()
        invite_id = invite.id

    with Session() as db:
        real_scalar = db.scalar
        calls = {"n": 0}

        def scalar_then_race(statement, *args, **kwargs):
            result = real_scalar(statement, *args, **kwargs)
            calls["n"] += 1
            if calls["n"] == 3:  # depois das checagens, outra requisição do mesmo sub aceita primeiro
                with Session() as other:
                    other.execute(update(CompanyMember).where(CompanyMember.id == invite_id).values(
                        auth0_sub="auth0|maria", status="ATIVO", invite_token_hash=None))
                    other.commit()
            return result

        monkeypatch.setattr(db, "scalar", scalar_then_race)
        service = TeamService(db)
        member = service.accept("auth0|maria", token)
        assert member.id == invite_id and member.status == "ATIVO" and service.events == []
    engine.dispose()


def test_accept_conflict_on_unique_sub_is_ja_vinculado(db_session, company, monkeypatch):
    customer_id, _ = company
    token = "z" * 43
    _member(db_session, customer_id, "auth0|tmp", status="CONVIDADO", email="m@x.com",
            invite_token_hash=hash_token(token), invite_expires_at=datetime.utcnow() + timedelta(days=1))
    db_session.execute(update(CompanyMember).where(CompanyMember.auth0_sub == "auth0|tmp")
                       .values(auth0_sub=None))
    db_session.commit()
    real_scalar = db_session.scalar
    calls = {"n": 0}

    def checks_miss(statement, *args, **kwargs):  # o sub do dono virou membro "em paralelo"
        calls["n"] += 1
        return None if calls["n"] in (2, 3) else real_scalar(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "scalar", checks_miss)
    with pytest.raises(ApiError) as exc:
        TeamService(db_session).accept(DONO_SUB, token)
    assert exc.value.status_code == 409 and exc.value.body == {"error": "JA_VINCULADO"}


# ---------- PATCH /me/team/{id} ----------

def test_patch_papel_applies_preset_and_emits_event(client, db_session, company):
    customer_id, _ = company
    alvo = _member(db_session, customer_id, "auth0|alvo", papel="LEITURA")
    _as(DONO_SUB)
    body = client.patch(f"/me/team/{alvo.id}", json={"papel": "FINANCEIRO"}).json()
    assert body["papel"] == "FINANCEIRO" and body["permissoes"] == preset("FINANCEIRO")
    body = client.patch(f"/me/team/{alvo.id}", json={"permissoes": ["ver_financeiro"], "limite_pagamento": 99.9}).json()
    assert body["permissoes"] == ["ver_financeiro"] and body["limite_pagamento"] == 99.9
    body = client.patch(f"/me/team/{alvo.id}", json={"limite_pagamento": None}).json()
    assert body["limite_pagamento"] is None
    events = _events(db_session)
    assert [e["acao"] for e in events] == ["ATUALIZADO"] * 3
    assert events[0] == {**events[0], "customer_id": customer_id, "member_id": alvo.id,
                         "papel": "FINANCEIRO", "permissoes": preset("FINANCEIRO"),
                         "event_type": "company.member_changed"}
    assert client.patch(f"/me/team/{alvo.id}", json={"permissoes": ["xpto"]}).status_code == 422


def test_patch_noop_has_no_event(client, db_session, company):
    alvo = _member(db_session, company[0], "auth0|alvo", papel="LEITURA")
    _as(DONO_SUB)
    assert client.patch(f"/me/team/{alvo.id}", json={"papel": "LEITURA"}).status_code == 200
    assert _events(db_session) == []


def test_suspend_and_reactivate(client, db_session, company):
    alvo = _member(db_session, company[0], "auth0|alvo")
    _as(DONO_SUB)
    assert client.patch(f"/me/team/{alvo.id}", json={"status": "SUSPENSO"}).json()["status"] == "SUSPENSO"
    _as("auth0|alvo")
    assert client.get("/me").json() == {"error": "MEMBRO_SUSPENSO"}
    _as(DONO_SUB)
    assert client.patch(f"/me/team/{alvo.id}", json={"status": "ATIVO"}).json()["status"] == "ATIVO"
    assert [e["acao"] for e in _events(db_session)] == ["SUSPENSO", "REATIVADO"]
    assert client.patch(f"/me/team/{alvo.id}", json={"status": "CONVIDADO"}).status_code == 422


def test_patch_pending_invite(client, db_session, company):
    _as(DONO_SUB)
    member_id = _invite(client).json()["membro"]["id"]
    blocked = client.patch(f"/me/team/{member_id}", json={"status": "SUSPENSO"})
    assert blocked.status_code == 409 and blocked.json() == {"error": "CONVITE_PENDENTE"}
    assert client.patch(f"/me/team/{member_id}", json={"papel": "ADMIN"}).json()["permissoes"] == ALL


def test_dono_is_protected(client, db_session, company):
    customer_id, dono_id = company
    alvo = _member(db_session, customer_id, "auth0|alvo")
    _member(db_session, customer_id, "auth0|adm", papel="ADMIN")
    _as("auth0|adm")
    for body in ({"status": "SUSPENSO"}, {"papel": "LEITURA"}, {"permissoes": []}, {"limite_pagamento": 1}):
        response = client.patch(f"/me/team/{dono_id}", json=body)
        assert response.status_code == 403 and response.json() == {"error": "DONO_PROTEGIDO"}
    assert client.delete(f"/me/team/{dono_id}").json() == {"error": "DONO_PROTEGIDO"}
    promote = client.patch(f"/me/team/{alvo.id}", json={"papel": "DONO"})
    assert promote.status_code == 403 and promote.json() == {"error": "SEM_PERMISSAO", "permissao": "dono"}
    _as(DONO_SUB)
    unique = client.patch(f"/me/team/{alvo.id}", json={"papel": "DONO"})
    assert unique.status_code == 409 and unique.json() == {"error": "DONO_UNICO"}
    self_edit = client.patch(f"/me/team/{dono_id}", json={"limite_pagamento": 1})
    assert self_edit.status_code == 403 and self_edit.json() == {"error": "AUTO_EDICAO"}
    db_session.expire_all()
    dono = db_session.get(CompanyMember, dono_id)
    assert (dono.papel, dono.status, dono.limite_pagamento) == ("DONO", "ATIVO", None)


def test_member_cannot_edit_or_remove_self(client, db_session, company):
    adm = _member(db_session, company[0], "auth0|adm", papel="ADMIN")
    _as("auth0|adm")
    for response in (client.patch(f"/me/team/{adm.id}", json={"limite_pagamento": None}),
                     client.delete(f"/me/team/{adm.id}")):
        assert response.status_code == 403 and response.json() == {"error": "AUTO_EDICAO"}


def test_other_company_ids_are_404(client, db_session, company):
    other = make_pj(db_session, sub="auth0|outra", cnpj="11444777000161")
    alheio = _member(db_session, other.id, "auth0|alheio")
    _as(DONO_SUB)
    for response in (client.patch(f"/me/team/{alheio.id}", json={"papel": "LEITURA"}),
                     client.delete(f"/me/team/{alheio.id}"),
                     client.delete("/me/team/999999")):
        assert response.status_code == 404 and response.json() == {"error": "MEMBRO_NAO_ENCONTRADO"}


def test_patch_with_stale_version_is_409(db_session, engine, company):
    customer_id, dono_id = company
    alvo = _member(db_session, customer_id, "auth0|alvo")
    db_session.get(CompanyMember, alvo.id)  # versão carregada na sessão
    with sessionmaker(bind=engine)() as other:  # outra requisição edita antes
        other.execute(update(CompanyMember).where(CompanyMember.id == alvo.id)
                      .values(limite_pagamento=5, updated_at=datetime.utcnow() + timedelta(seconds=1)))
        other.commit()
    with pytest.raises(ApiError) as exc:
        TeamService(db_session).update(db_session.get(CompanyMember, dono_id), alvo.id,
                                       MemberPatch(limite_pagamento=10))
    assert exc.value.body == {"error": "CONFLITO_CONCORRENTE"}


def test_writes_never_touch_dono_even_if_check_is_bypassed(db_session, company, monkeypatch):
    """O `papel <> 'DONO'` no WHERE garante o DONO mesmo se a checagem em Python for vencida por corrida."""
    customer_id, dono_id = company
    adm = _member(db_session, customer_id, "auth0|adm", papel="ADMIN")
    dono = db_session.get(CompanyMember, dono_id)
    monkeypatch.setattr(TeamService, "_target", lambda self, actor, member_id: dono)
    service = TeamService(db_session)
    with pytest.raises(ApiError) as exc:
        service.update(adm, dono_id, MemberPatch(status="SUSPENSO"))
    assert exc.value.status_code == 409
    with pytest.raises(ApiError) as exc:
        service.remove(adm, dono_id)
    assert exc.value.status_code == 404
    db_session.expire_all()
    remaining = db_session.scalars(select(CompanyMember).where(CompanyMember.papel == "DONO")).all()
    assert [(d.id, d.status) for d in remaining] == [(dono_id, "ATIVO")]


# ---------- DELETE /me/team/{id} ----------

def test_delete_revokes_invite_and_removes_member(client, db_session, company):
    customer_id, _ = company
    _as(DONO_SUB)
    created = _invite(client)
    invite_id, token = created.json()["membro"]["id"], _token(created)
    membro_id = _member(db_session, customer_id, "auth0|alvo").id
    assert client.delete(f"/me/team/{invite_id}").status_code == 204
    assert client.delete(f"/me/team/{membro_id}").status_code == 204
    assert [m["papel"] for m in client.get("/me/team").json()] == ["DONO"]
    _as("auth0|maria", {"read:self"})
    assert client.post(f"/me/team/invites/{token}/accept").status_code == 404  # convite revogado
    _as("auth0|alvo")
    assert client.get("/me").json()["customer_id"] is None  # perdeu o acesso
    events = _events(db_session)
    assert [(e["acao"], e["member_id"]) for e in events] == [
        ("CONVIDADO", invite_id), ("REMOVIDO", invite_id), ("REMOVIDO", membro_id)]


# ---------- evento e métrica ----------

def test_member_changed_published_via_outbox(client, db_session, company, broker):
    from app.events import EventPublisher

    original = client.app.state.publisher
    client.app.state.publisher = EventPublisher("amqp://localhost/")
    try:
        _as(DONO_SUB)
        assert _invite(client).status_code == 201
    finally:
        client.app.state.publisher = original
    publish = broker.exchange.publish.await_args
    assert publish.kwargs["routing_key"] == "company.member_changed"
    db_session.expire_all()
    row = db_session.scalar(select(OutboxEvent).where(OutboxEvent.routing_key == "company.member_changed"))
    assert row.published_at is not None


def test_team_members_gauge(client, db_session, company):
    _as(DONO_SUB)
    refresh_team_members(db_session)
    assert _gauge("DONO", "ATIVO") == 1 and _gauge("LEITURA", "SUSPENSO") == 0
    token = _token(_invite(client))
    assert _gauge("FINANCEIRO", "CONVIDADO") == 1
    _as("auth0|maria", {"read:self"})
    client.post(f"/me/team/invites/{token}/accept")
    assert _gauge("FINANCEIRO", "CONVIDADO") == 0 and _gauge("FINANCEIRO", "ATIVO") == 1
    body = client.get("/metrics").text
    assert 'team_members_total{papel="OPERADOR",status="SUSPENSO"} 0.0' in body
    assert 'events_published_total{result="ok",routing_key="company.member_changed"}' in body


def test_gauge_refresh_failures_are_logged(db_session, monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(db_session, "execute", boom)
    refresh_team_members(db_session)
    assert "team_members_total" in caplog.text

    from app import main

    monkeypatch.setattr(main, "SessionLocal", boom)
    _init_team_gauge()


def test_first_onboarding_put_updates_gauge(client):
    before = _gauge("DONO", "ATIVO")
    from tests.test_onboarding import _body

    _as("auth0|novo-dono")
    assert client.put("/me/onboarding", json=_body()).status_code == 200
    assert _gauge("DONO", "ATIVO") == before + 1


def test_invite_url_helper(monkeypatch):
    monkeypatch.setattr(settings, "front_url", "")
    assert service_module.invite_url("abc") == "https://erp-banking-front.vercel.app/convite/abc"
