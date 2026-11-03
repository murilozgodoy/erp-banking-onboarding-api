"""Equipe (PR 1): modelo, migração do DONO, resolver do `sub` e GET /me com `membro`."""
import threading
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.dialects.postgresql import psycopg
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.config.database import Base
from app.config.migrations import run_data_migrations, run_migrations
from app.core.errors import ApiError
from app.core.security import Principal, require_auth
from app.main import app
from app.models import CompanyMember, Customer
from app.team import members as members_module
from app.team.members import ensure_owner_member, owner_backfill_statement
from app.team.permissions import (
    PERMISSOES,
    canonical,
    effective,
    preset,
    unknown,
)
from app.team.resolver import resolve
from tests.factories import make_pj
from tests.test_onboarding import EMPRESA, _body

ALL = list(PERMISSOES)


def _as(subject, permissions=("read:self", "write:self")):
    app.dependency_overrides[require_auth] = lambda: Principal(
        token="t", subject=subject, permissions=frozenset(permissions)
    )


def _member(db, customer, sub, papel="FINANCEIRO", status="ATIVO", email="func@padaria.com", **kw):
    member = CompanyMember(
        customer_id=customer.id, auth0_sub=sub, email=email, nome="Fulano", papel=papel,
        permissoes=kw.pop("permissoes", preset(papel)), status=status, created_by="auth0|pj", **kw,
    )
    db.add(member)
    db.commit()
    return member


def _donos(db, customer_id=None):
    query = select(CompanyMember).where(CompanyMember.papel == "DONO").order_by(CompanyMember.customer_id)
    if customer_id is not None:
        query = query.where(CompanyMember.customer_id == customer_id)
    db.expire_all()
    return list(db.scalars(query))


# ---------- permissões ----------

def test_presets_match_contract():
    assert preset("DONO") == ALL and preset("ADMIN") == ALL
    assert preset("FINANCEIRO") == [
        "ver_financeiro", "pagar", "aprovar_pagamentos", "pedir_credito", "usar_assistente"]
    assert preset("OPERADOR") == ["ver_financeiro", "pagar", "gerenciar_estoque", "usar_assistente"]
    assert preset("LEITURA") == ["ver_financeiro"]


def test_permission_helpers():
    assert canonical(["usar_assistente", "pagar", "pagar", "xpto"]) == ["pagar", "usar_assistente"]
    assert unknown(["pagar", "voar", "abc"]) == ["abc", "voar"]
    assert effective("DONO", []) == ALL
    assert effective("LEITURA", None) == []


# ---------- modelo / índices ----------

def test_unique_indexes(db_session):
    customer = make_pj(db_session)
    _member(db_session, customer, None, email="a@x.com", status="CONVIDADO")
    _member(db_session, customer, None, email="b@x.com", status="CONVIDADO")  # vários sub NULL
    _member(db_session, customer, "auth0|dono", papel="DONO", email="dono@x.com")
    with pytest.raises(IntegrityError):  # um DONO por empresa
        _member(db_session, customer, "auth0|dono2", papel="DONO", email="dono2@x.com")
    db_session.rollback()
    with pytest.raises(IntegrityError):  # sub único
        _member(db_session, customer, "auth0|dono", email="c@x.com")
    db_session.rollback()
    with pytest.raises(IntegrityError):  # e-mail único entre ATIVO/CONVIDADO da empresa
        _member(db_session, customer, None, email="a@x.com")
    db_session.rollback()
    # suspenso não conta para o e-mail único
    _member(db_session, customer, None, email="a@x.com", status="SUSPENSO")


# ---------- migração ----------

def test_migration_creates_dono_idempotently(engine, db_session):
    with_sub = make_pj(db_session, sub="auth0|a", cnpj="11222333000181")
    seeded = make_pj(db_session, sub=None, cnpj="11444777000161")  # ex.: Aurora semeada sem sub
    db_session.add(Customer(nome="Ana", cpf="12345678900", email="a@x.com", telefone="11999990000"))
    has_dono = make_pj(db_session, sub="auth0|c", cnpj="45723174000110")
    _member(db_session, has_dono, "auth0|c", papel="DONO", email="dono@c.com")

    run_migrations(engine)
    run_migrations(engine)  # idempotente

    donos = _donos(db_session)
    assert [(d.customer_id, d.auth0_sub) for d in donos] == [
        (with_sub.id, "auth0|a"), (seeded.id, None), (has_dono.id, "auth0|c")]
    first = donos[0]
    assert first.status == "ATIVO" and first.permissoes == ALL and first.limite_pagamento is None
    assert first.email == "contato@padaria.com" and first.nome == "Padaria Boa LTDA"
    assert first.created_by == "migracao"


def test_migration_dono_without_sub_when_sub_already_member(engine, db_session):
    company = make_pj(db_session, sub="auth0|a", cnpj="11222333000181")
    _member(db_session, company, "auth0|a", papel="DONO", email="dono@a.com")
    other = make_pj(db_session, sub="auth0|b", cnpj="11444777000161")
    _member(db_session, company, "auth0|b")  # sub de b já é membro de a (caso anômalo)
    run_data_migrations(engine)
    assert _donos(db_session, other.id)[0].auth0_sub is None


def test_data_migration_failure_is_logged_not_raised(caplog):
    engine = MagicMock()
    engine.dialect.name = "sqlite"
    engine.begin.side_effect = RuntimeError("db down")
    run_data_migrations(engine)
    assert "company_members" in caplog.text


def test_postgres_backfill_statement():
    sql = str(owner_backfill_statement("postgresql").compile(dialect=psycopg.dialect()))
    assert sql.startswith("INSERT INTO company_members")
    assert "NOT (EXISTS" in sql and sql.endswith("ON CONFLICT DO NOTHING")
    assert "::JSON" in sql


# ---------- resolver ----------

def test_resolver_owner_member_suspended_none(db_session):
    company = make_pj(db_session, sub="auth0|dono")
    _member(db_session, company, "auth0|func")
    _member(db_session, company, "auth0|susp", status="SUSPENSO", email="s@x.com")

    owner = resolve(db_session, "auth0|dono")
    assert owner.customer.id == company.id and owner.member.papel == "DONO" and owner.is_owner

    member = resolve(db_session, "auth0|func")
    assert member.customer.id == company.id and member.member.papel == "FINANCEIRO"
    assert not member.is_owner

    with pytest.raises(ApiError) as exc:
        resolve(db_session, "auth0|susp")
    assert exc.value.status_code == 403 and exc.value.body == {"error": "MEMBRO_SUSPENSO"}

    nobody = resolve(db_session, "auth0|ninguem")
    assert nobody.customer is None and nobody.member is None


def test_stale_dono_row_does_not_grant_access(db_session):
    company = make_pj(db_session, sub="auth0|novo")
    _member(db_session, company, "auth0|antigo", papel="DONO", email="dono@x.com")
    # o dono mudou por UPDATE manual: o sub antigo não resolve mais (customers.auth0_sub é a verdade)
    assert resolve(db_session, "auth0|antigo").customer is None
    assert resolve(db_session, "auth0|novo").member.auth0_sub == "auth0|novo"


# ---------- GET /me ----------

def test_me_as_active_member(client, db_session):
    company = make_pj(db_session, sub="auth0|dono", status="APROVADO")
    member = _member(db_session, company, "auth0|func", papel="OPERADOR", limite_pagamento=1500.5)
    _as("auth0|func")
    body = client.get("/me").json()
    assert body["customer_id"] == company.id and body["onboarding_status"] == "APROVADO"
    assert body["empresa"]["cnpj"] == "11222333000181"
    assert body["membro"] == {
        "id": member.id, "nome": "Fulano", "email": "func@padaria.com", "papel": "OPERADOR",
        "permissoes": ["ver_financeiro", "pagar", "gerenciar_estoque", "usar_assistente"],
        "limite_pagamento": 1500.5, "status": "ATIVO",
    }


def test_me_suspended_member_is_403(client, db_session):
    company = make_pj(db_session, sub="auth0|dono")
    _member(db_session, company, "auth0|susp", status="SUSPENSO")
    _as("auth0|susp")
    for path in ("/me", "/me/onboarding"):
        response = client.get(path)
        assert response.status_code == 403
        assert response.json() == {"error": "MEMBRO_SUSPENSO"}
    assert client.put("/me/onboarding", json=_body()).json() == {"error": "MEMBRO_SUSPENSO"}


def test_me_owner_sub_set_later_syncs_dono(client, engine, db_session):
    seeded = make_pj(db_session, sub=None)
    run_migrations(engine)
    assert _donos(db_session, seeded.id)[0].auth0_sub is None
    db_session.execute(update(Customer).where(Customer.id == seeded.id).values(auth0_sub="auth0|aurora"))
    db_session.commit()

    _as("auth0|aurora")
    body = client.get("/me").json()
    assert body["customer_id"] == seeded.id
    assert body["membro"]["papel"] == "DONO" and body["membro"]["permissoes"] == ALL
    donos = _donos(db_session, seeded.id)
    assert len(donos) == 1 and donos[0].auth0_sub == "auth0|aurora"


def test_me_creates_missing_dono(client, db_session):
    company = make_pj(db_session, sub="auth0|test")
    assert _donos(db_session) == []
    body = client.get("/me").json()
    assert body["membro"]["papel"] == "DONO"
    assert client.get("/me").json()["membro"]["id"] == body["membro"]["id"]  # não duplica
    assert [d.auth0_sub for d in _donos(db_session, company.id)] == ["auth0|test"]


def test_owner_sync_clears_stale_dono_of_previous_company(db_session):
    old = make_pj(db_session, sub="auth0|x", cnpj="11222333000181")
    _member(db_session, old, "auth0|x", papel="DONO", email="dono@old.com")
    db_session.execute(update(Customer).where(Customer.id == old.id).values(auth0_sub=None))
    new = make_pj(db_session, sub="auth0|x", cnpj="11444777000161")
    assert resolve(db_session, "auth0|x").member.customer_id == new.id
    assert _donos(db_session, old.id)[0].auth0_sub is None


def test_owner_sync_conflict_with_member_keeps_dono_without_sub(db_session, caplog):
    company = make_pj(db_session, sub="auth0|a", cnpj="11222333000181")
    owner = make_pj(db_session, sub="auth0|b", cnpj="11444777000161")
    _member(db_session, company, "auth0|b")  # o sub do dono de `owner` está em outra empresa
    membership = resolve(db_session, "auth0|b")
    assert membership.customer.id == owner.id
    assert membership.member.papel == "DONO" and membership.member.auth0_sub is None
    assert "sem o auth0_sub" in caplog.text


def test_concurrent_first_calls_do_not_duplicate_dono(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    with Session() as db:
        customer_id = make_pj(db, sub="auth0|race").id

    barrier = threading.Barrier(2, timeout=10)
    real_find = members_module.find_dono
    first_read = threading.local()

    def find_then_wait(db, cid):
        found = real_find(db, cid)
        if not getattr(first_read, "done", False):
            first_read.done = True
            barrier.wait()  # as duas requisições leram "sem DONO" antes de qualquer escrita
        return found

    monkeypatch.setattr(members_module, "find_dono", find_then_wait)
    results, errors = [], []

    def call():
        try:
            with Session() as db:
                member = ensure_owner_member(db, db.get(Customer, customer_id))
                results.append((member.id, member.auth0_sub))
        except Exception as exc:  # pragma: no cover - só em falha do teste
            errors.append(exc)

    threads = [threading.Thread(target=call) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert errors == []
    assert len(results) == 2 and results[0] == results[1] and results[0][1] == "auth0|race"
    with Session() as db:
        assert db.scalar(select(func.count()).select_from(CompanyMember)) == 1
    engine.dispose()


def test_ensure_owner_rereads_after_integrity_error(db_session, monkeypatch):
    """Simula a corrida no PostgreSQL: o INSERT do perdedor falha no índice único e ele relê."""
    customer = make_pj(db_session, sub="auth0|r")
    _member(db_session, customer, "auth0|r", papel="DONO", email="dono@x.com")
    calls = {"n": 0}
    real_find = members_module.find_dono

    def stale_then_real(db, cid):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_find(db, cid)

    def failing_insert(dialect, customer_id=None):
        raise IntegrityError("INSERT", {}, Exception("unique"))

    monkeypatch.setattr(members_module, "find_dono", stale_then_real)
    monkeypatch.setattr(members_module, "owner_backfill_statement", failing_insert)
    member = ensure_owner_member(db_session, customer)
    assert member.auth0_sub == "auth0|r" and calls["n"] == 2


# ---------- PUT /me/onboarding ----------

def test_first_put_creates_dono_in_same_transaction(client, db_session):
    assert client.put("/me/onboarding", json=_body()).status_code == 200
    assert client.put("/me/onboarding", json=_body()).status_code == 200  # não cria outro
    customer = db_session.scalar(select(Customer).where(Customer.auth0_sub == "auth0|test"))
    donos = _donos(db_session)
    assert len(donos) == 1
    dono = donos[0]
    assert (dono.customer_id, dono.auth0_sub, dono.status) == (customer.id, "auth0|test", "ATIVO")
    assert dono.email == EMPRESA["email"] and dono.nome == EMPRESA["razao_social"]
    assert dono.permissoes == ALL and dono.created_by == "auth0|test"
    assert client.get("/me").json()["membro"]["id"] == dono.id


def test_put_onboarding_by_member_is_forbidden_but_get_works(client, db_session):
    company = make_pj(db_session, sub="auth0|dono", status="RASCUNHO")
    _member(db_session, company, "auth0|func", papel="ADMIN")
    _as("auth0|func")
    response = client.put("/me/onboarding", json=_body())
    assert response.status_code == 403
    assert response.json() == {"error": "SEM_PERMISSAO", "permissao": "dono"}
    got = client.get("/me/onboarding")
    assert got.status_code == 200 and got.json()["empresa"]["cnpj"] == "11222333000181"
    # o membro não criou outra empresa
    assert db_session.scalar(select(func.count()).select_from(Customer)) == 1


def test_put_onboarding_conflict_when_sub_is_member_elsewhere(client, db_session, monkeypatch):
    """Corrida PUT x aceite: o DONO novo bate no índice único de auth0_sub → 409, nada é criado."""
    from app.routers import me as me_router
    from app.team.resolver import Membership

    company = make_pj(db_session, sub="auth0|dono")
    _member(db_session, company, "auth0|test")
    # resolver "atrasado": ainda não viu o aceite que vinculou o sub
    monkeypatch.setattr(me_router, "resolve", lambda db, sub: Membership(None, None))
    response = client.put("/me/onboarding", json=_body(empresa={**EMPRESA, "cnpj": "11444777000161"}))
    assert response.status_code == 409
    assert db_session.scalar(select(func.count()).select_from(Customer)) == 1
