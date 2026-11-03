import json

import pytest
from prometheus_client import REGISTRY

from app.core.security import Principal, require_auth
from app.events import EventPublisher
from app.main import app
from app.models import Customer
from app.schemas.onboarding import normalize_cnpj
from tests.test_templates import respostas_validas

EMPRESA = {
    "razao_social": "Padaria Boa LTDA", "nome_fantasia": "Padaria Boa", "cnpj": "11.222.333/0001-81",
    "email": "contato@padaria.com", "telefone": "11988887777", "cidade": "São Paulo",
    "estado": "sp", "fundacao_ano": 2015, "funcionarios": 12,
}


def _as(permissions, subject="auth0|test"):
    app.dependency_overrides[require_auth] = lambda: Principal(
        token="t", subject=subject, permissions=frozenset(permissions)
    )


def _metric(name, labels=None):
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


def _body(enviar=False, **changes):
    body = {"empresa": dict(EMPRESA), "segmento": "alimentacao",
            "respostas": respostas_validas("alimentacao"), "observacoes": "Padaria de bairro",
            "enviar": enviar}
    body.update(changes)
    return body


@pytest.fixture()
def live_publisher(client, broker):
    original = client.app.state.publisher
    client.app.state.publisher = EventPublisher("amqp://localhost/")
    yield broker
    client.app.state.publisher = original


def test_get_onboarding_without_customer(client):
    assert client.get("/me/onboarding").json() == {
        "empresa": None, "segmento": None, "respostas": {}, "observacoes": None,
        "onboarding_status": "NAO_INICIADO", "updated_at": None,
        "review_comment": None, "reviewed_at": None,
    }


def test_permissions(client):
    _as({"read:customers"})
    assert client.get("/me/onboarding").status_code == 403
    assert client.put("/me/onboarding", json={}).status_code == 403
    _as({"read:self"})
    assert client.put("/me/onboarding", json={}).status_code == 403


def test_partial_draft_then_get(client, db_session):
    before = _metric("onboarding_drafts_saved_total")
    response = client.put("/me/onboarding", json={"empresa": {"razao_social": "Padaria Boa LTDA"},
                                                   "respostas": {"faturamento_mensal": 1}})
    assert response.status_code == 200
    body = response.json()
    assert body["onboarding_status"] == "RASCUNHO"
    assert body["empresa"]["razao_social"] == "Padaria Boa LTDA" and body["empresa"]["cnpj"] is None
    assert body["respostas"] == {"faturamento_mensal": 1} and body["updated_at"]
    assert _metric("onboarding_drafts_saved_total") == before + 1

    assert client.get("/me/onboarding").json() == body
    me = client.get("/me").json()
    assert me["onboarding_status"] == "RASCUNHO" and me["customer_id"]
    customer = db_session.get(Customer, me["customer_id"])
    assert customer.tipo_pessoa == "PJ" and customer.cpf is None and customer.auth0_sub == "auth0|test"
    assert customer.nome == "Padaria Boa LTDA"


def test_empty_draft(client):
    response = client.put("/me/onboarding", json={})
    assert response.status_code == 200
    assert response.json()["onboarding_status"] == "RASCUNHO"
    assert response.json()["empresa"]["razao_social"] is None


@pytest.mark.parametrize("empresa", [
    {"cnpj": "11.222.333/0001-82"}, {"cnpj": "1122233300018"}, {"cnpj": "11111111111111"},
    {"estado": "XX"}, {"email": "nao-e-email"}, {"fundacao_ano": 3000}, {"funcionarios": -1},
])
def test_invalid_empresa_is_422_even_in_draft(client, empresa):
    assert client.put("/me/onboarding", json={"empresa": empresa}).status_code == 422


def test_unknown_segmento_is_422(client):
    assert client.put("/me/onboarding", json={"segmento": "cassino"}).status_code == 422


def test_normalize_cnpj():
    assert normalize_cnpj("11.222.333/0001-81") == "11222333000181"
    assert normalize_cnpj("00000000000191") == "00000000000191"


def test_submit_publishes_event(client, live_publisher):
    labels = {"segmento": "alimentacao"}
    before = _metric("onboarding_submissions_total", labels)
    response = client.put("/me/onboarding", json=_body(enviar=True))
    assert response.status_code == 200
    body = response.json()
    assert body["onboarding_status"] == "EM_ANALISE"
    assert body["empresa"]["cnpj"] == "11222333000181" and body["empresa"]["estado"] == "SP"
    assert _metric("onboarding_submissions_total", labels) == before + 1

    call = live_publisher.exchange.publish.await_args
    assert call.kwargs["routing_key"] == "customer.onboarding_submitted"
    event = json.loads(call.args[0].body)
    customer_id = client.get("/me").json()["customer_id"]
    assert event["event_type"] == "customer.onboarding_submitted"
    assert event["event_id"] and event["occurred_at"]
    assert event["customer_id"] == customer_id and event["auth0_sub"] == "auth0|test"
    assert event["segmento"] == "alimentacao"
    assert event["empresa"] == body["empresa"]
    assert event["respostas"] == respostas_validas("alimentacao")
    assert event["observacoes"] == "Padaria de bairro"


def test_draft_then_submit_keeps_customer_and_sets_submitted_at(client, db_session):
    draft = client.put("/me/onboarding", json=_body())
    customer_id = client.get("/me").json()["customer_id"]
    assert draft.json()["onboarding_status"] == "RASCUNHO"
    assert client.put("/me/onboarding", json=_body(enviar=True)).status_code == 200
    assert client.get("/me").json()["customer_id"] == customer_id
    customer = db_session.get(Customer, customer_id)
    assert customer.business_profile.submitted_at is not None


def test_submit_incomplete_lists_fields(client):
    body = _body(enviar=True, empresa={"razao_social": "X"}, respostas={"faturamento_mensal": -5})
    response = client.put("/me/onboarding", json=body)
    assert response.status_code == 422
    campos = {e["campo"] for e in response.json()["campos"]}
    assert {"empresa.cnpj", "empresa.email", "empresa.telefone", "empresa.cidade", "empresa.estado",
            "faturamento_mensal"} <= campos
    assert "empresa.razao_social" not in campos
    assert client.get("/me").json()["customer_id"] is None  # nada foi salvo

    response = client.put("/me/onboarding", json=_body(enviar=True, segmento=None))
    assert response.json()["campos"] == [{"campo": "segmento", "erro": "Escolha o segmento."}]


@pytest.mark.parametrize("status", ["EM_ANALISE", "ANALISE_MANUAL", "APROVADO"])
def test_locked_statuses_return_409(client, db_session, status):
    assert client.put("/me/onboarding", json=_body(enviar=True)).status_code == 200
    customer = db_session.get(Customer, client.get("/me").json()["customer_id"])
    customer.onboarding_status = status
    db_session.commit()
    assert client.put("/me/onboarding", json=_body()).status_code == 409
    assert client.put("/me/onboarding", json=_body(enviar=True)).status_code == 409


def test_resubmit_after_reprovado_clears_review(client, db_session):
    client.put("/me/onboarding", json=_body(enviar=True))
    customer = db_session.get(Customer, client.get("/me").json()["customer_id"])
    customer.onboarding_status = "REPROVADO"
    customer.business_profile.analise = {"score": 100}
    customer.business_profile.reviewed_by = "auth0|analista"
    db_session.commit()

    response = client.put("/me/onboarding", json=_body(enviar=True, observacoes="Agora com delivery"))
    assert response.status_code == 200 and response.json()["onboarding_status"] == "EM_ANALISE"
    db_session.expire_all()
    assert customer.business_profile.analise is None and customer.business_profile.reviewed_by is None


def test_duplicate_cnpj_from_another_customer_is_409(client):
    assert client.put("/me/onboarding", json=_body()).status_code == 200
    _as({"read:self", "write:self"}, subject="auth0|outro")
    response = client.put("/me/onboarding", json=_body())
    assert response.status_code == 409
    assert "CNPJ" in response.json()["detail"]
    _as({"read:self", "write:self"})  # o dono pode salvar de novo com o próprio CNPJ
    assert client.put("/me/onboarding", json=_body()).status_code == 200


def test_integrity_error_race_is_409(client, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    def boom(self):
        raise IntegrityError("insert", {}, Exception("unique"))

    monkeypatch.setattr(Session, "commit", boom)
    assert client.put("/me/onboarding", json=_body()).status_code == 409


def test_pj_does_not_publish_customer_created(client, live_publisher):
    client.put("/me/onboarding", json=_body())
    client.put("/me/onboarding", json=_body(enviar=True))
    keys = [c.kwargs["routing_key"] for c in live_publisher.exchange.publish.await_args_list]
    assert keys == ["customer.onboarding_submitted"]


def test_submission_series_initialized(client):
    body = client.get("/metrics").text
    for segmento in ("varejo", "alimentacao", "servicos", "saude", "tecnologia", "industria",
                     "agro", "construcao", "outro"):
        assert f'onboarding_submissions_total{{segmento="{segmento}"}} ' in body
    assert "onboarding_drafts_saved_total " in body
    assert 'events_published_total{result="ok",routing_key="customer.onboarding_submitted"} ' in body
