"""review_comment/reviewed_at em GET/PUT /me/onboarding (só após revisão manual)."""
from datetime import datetime

from tests.factories import make_pj

SUB = "auth0|test"
REVIEW = {"reviewed_by": "auth0|analista", "review_comment": "Faltou faturamento",
          "reviewed_at": datetime(2026, 11, 2, 10, 0)}


def test_reprovado_after_review_exposes_comment(client, db_session):
    make_pj(db_session, sub=SUB, status="REPROVADO", **REVIEW)
    body = client.get("/me/onboarding").json()
    assert body["review_comment"] == "Faltou faturamento"
    assert body["reviewed_at"].startswith("2026-11-02T10:00")


def test_aprovado_after_review_exposes_comment(client, db_session):
    make_pj(db_session, sub=SUB, status="APROVADO", **REVIEW)
    body = client.get("/me/onboarding").json()
    assert body["review_comment"] == "Faltou faturamento"
    assert body["reviewed_at"] is not None


def test_aprovado_automatico_has_no_review(client, db_session):
    make_pj(db_session, sub=SUB, status="APROVADO")
    body = client.get("/me/onboarding").json()
    assert body["review_comment"] is None and body["reviewed_at"] is None


def test_other_status_hides_stale_review(client, db_session):
    make_pj(db_session, sub=SUB, status="ANALISE_MANUAL", **REVIEW)
    body = client.get("/me/onboarding").json()
    assert body["review_comment"] is None and body["reviewed_at"] is None


def test_nao_iniciado_and_put_include_null_fields(client):
    body = client.get("/me/onboarding").json()
    assert body["review_comment"] is None and body["reviewed_at"] is None
    put = client.put("/me/onboarding", json={"empresa": {"razao_social": "X LTDA"}}).json()
    assert "review_comment" in put and put["review_comment"] is None
    assert put["reviewed_at"] is None


def test_decision_flow_exposes_comment(client, db_session):
    customer = make_pj(db_session, sub=SUB, status="ANALISE_MANUAL")
    client.post(f"/onboarding/reviews/{customer.id}/decision",
                json={"decisao": "REPROVADO", "comentario": "Documentos ilegíveis"})
    body = client.get("/me/onboarding").json()
    assert body["onboarding_status"] == "REPROVADO"
    assert body["review_comment"] == "Documentos ilegíveis"
    assert body["reviewed_at"] is not None
