import json
from datetime import datetime

from app.core.security import Principal, require_auth
from app.events import EventPublisher
from app.main import app
from tests.factories import make_pj


def _as(permissions, subject="auth0|analista"):
    app.dependency_overrides[require_auth] = lambda: Principal(
        token="t", subject=subject, permissions=frozenset(permissions)
    )


def test_reviews_queue_defaults_to_analise_manual(client, db_session):
    first = make_pj(db_session, sub="a", cnpj="11222333000181", status="ANALISE_MANUAL",
                    analise={"score": 610, "faixa_risco": "MEDIO", "gerado_por": "regras",
                             "status": "ANALISE_MANUAL"},
                    submitted_at=datetime(2026, 11, 1, 10, 0))
    make_pj(db_session, sub="b", cnpj="11444777000161", status="EM_ANALISE")
    second = make_pj(db_session, sub="c", cnpj="00000000000191", status="ANALISE_MANUAL",
                     submitted_at=datetime(2026, 11, 2, 10, 0))

    body = client.get("/onboarding/reviews").json()
    assert [item["customer_id"] for item in body] == [first.id, second.id]
    assert body[0] == {
        "customer_id": first.id,
        "empresa": {
            "razao_social": "Padaria Boa LTDA", "nome_fantasia": "Padaria Boa",
            "cnpj": "11222333000181", "email": "contato@padaria.com", "telefone": "11988887777",
            "cidade": "São Paulo", "estado": "SP", "fundacao_ano": 2015, "funcionarios": 12,
        },
        "segmento": "alimentacao",
        "observacoes": "Padaria de bairro",
        "analise": {"score": 610, "faixa_risco": "MEDIO", "gerado_por": "regras",
                    "status": "ANALISE_MANUAL"},
        "submitted_at": "2026-11-01T10:00:00",
    }
    em_analise = client.get("/onboarding/reviews", params={"status": "EM_ANALISE"}).json()
    assert len(em_analise) == 1
    assert client.get("/onboarding/reviews", params={"status": "XPTO"}).status_code == 422


def test_reviews_require_permission(client):
    _as({"read:customers", "read:self"})
    assert client.get("/onboarding/reviews").status_code == 403
    assert client.post("/onboarding/reviews/1/decision", json={"decisao": "APROVADO"}).status_code == 403


def test_decision_approves_and_publishes(client, db_session, broker):
    customer = make_pj(db_session, status="ANALISE_MANUAL")
    _as({"review:onboarding"}, subject="auth0|analista")
    original = client.app.state.publisher
    client.app.state.publisher = EventPublisher("amqp://localhost/")
    try:
        response = client.post(f"/onboarding/reviews/{customer.id}/decision",
                               json={"decisao": "APROVADO", "comentario": "ok, padrão do segmento"})
    finally:
        client.app.state.publisher = original
    assert response.status_code == 200
    body = response.json()
    assert body["onboarding_status"] == "APROVADO" and body["reviewer"] == "auth0|analista"

    db_session.expire_all()
    assert customer.onboarding_status == "APROVADO"
    assert customer.business_profile.reviewed_by == "auth0|analista"
    assert customer.business_profile.review_comment == "ok, padrão do segmento"
    assert customer.business_profile.reviewed_at is not None

    call = broker.exchange.publish.await_args
    assert call.kwargs["routing_key"] == "customer.onboarding_reviewed"
    event = json.loads(call.args[0].body)
    assert {k: event[k] for k in ("event_type", "customer_id", "decisao", "comentario", "reviewer")} == {
        "event_type": "customer.onboarding_reviewed", "customer_id": customer.id,
        "decisao": "APROVADO", "comentario": "ok, padrão do segmento", "reviewer": "auth0|analista",
    }
    assert event["event_id"] and event["occurred_at"]


def test_decision_reject_without_comment(client, db_session):
    customer = make_pj(db_session, status="ANALISE_MANUAL")
    response = client.post(f"/onboarding/reviews/{customer.id}/decision", json={"decisao": "REPROVADO"})
    assert response.status_code == 200
    assert response.json()["onboarding_status"] == "REPROVADO"


def test_decision_conflicts_and_not_found(client, db_session):
    customer = make_pj(db_session, status="EM_ANALISE")
    assert client.post(f"/onboarding/reviews/{customer.id}/decision",
                       json={"decisao": "APROVADO"}).status_code == 409
    assert client.post("/onboarding/reviews/9999/decision", json={"decisao": "APROVADO"}).status_code == 404
    assert client.post(f"/onboarding/reviews/{customer.id}/decision",
                       json={"decisao": "TALVEZ"}).status_code == 422


def _gauge():
    from prometheus_client import REGISTRY

    return REGISTRY.get_sample_value("onboarding_manual_queue_size")


def test_reviews_metric_and_queue_gauge(client, db_session):
    from prometheus_client import REGISTRY

    a = make_pj(db_session, sub="a", cnpj="11222333000181", status="ANALISE_MANUAL")
    make_pj(db_session, sub="b", cnpj="11444777000161", status="ANALISE_MANUAL")
    labels = {"decisao": "REPROVADO"}
    before = REGISTRY.get_sample_value("onboarding_reviews_total", labels)
    client.post(f"/onboarding/reviews/{a.id}/decision", json={"decisao": "REPROVADO"})
    assert REGISTRY.get_sample_value("onboarding_reviews_total", labels) == before + 1
    assert _gauge() == 1
    body = client.get("/metrics").text
    assert 'onboarding_reviews_total{decisao="APROVADO"} ' in body
    assert "onboarding_manual_queue_size " in body


def test_gauge_startup_failure_is_logged(monkeypatch):
    from app import main

    def broken():
        raise RuntimeError("db fora")

    monkeypatch.setattr(main, "SessionLocal", broken)
    main._init_manual_queue_gauge()  # não propaga
