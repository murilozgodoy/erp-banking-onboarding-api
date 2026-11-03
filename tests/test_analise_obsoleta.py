"""Análise atrasada de uma submissão anterior não pode ser aplicada ao reenvio (source_event_id)."""
import json
import uuid

import pytest

from app.config.migrations import migration_statements
from app.events import EventPublisher
from app.messaging.handlers import handle_analysis_completed
from app.models import Customer, ProcessedEvent
from tests.factories import make_pj
from tests.test_onboarding import _body

RK = "business.analysis_completed"


def _event(customer_id, source_event_id=None, status="APROVADO"):
    event = {"event_id": str(uuid.uuid4()), "event_type": RK, "occurred_at": "2026-11-03T12:00:00+00:00",
             "customer_id": customer_id, "status": status, "score": 742.0,
             "faixa_risco": "MEDIO", "gerado_por": "regras"}
    if source_event_id is not None:
        event["source_event_id"] = source_event_id
    return event


@pytest.fixture()
def live_publisher(client, broker):
    original = client.app.state.publisher
    client.app.state.publisher = EventPublisher("amqp://localhost/")
    yield broker
    client.app.state.publisher = original


def _published_submissions(broker):
    return [json.loads(c.args[0].body) for c in broker.exchange.publish.await_args_list
            if c.kwargs["routing_key"] == "customer.onboarding_submitted"]


def test_submit_stores_published_event_id(client, db_session, live_publisher):
    assert client.put("/me/onboarding", json=_body(enviar=True)).status_code == 200
    (event,) = _published_submissions(live_publisher)
    customer = db_session.get(Customer, client.get("/me").json()["customer_id"])
    assert customer.business_profile.submission_event_id == event["event_id"]


def test_draft_keeps_last_submission_event_id(client, db_session):
    client.put("/me/onboarding", json=_body())
    customer = db_session.get(Customer, client.get("/me").json()["customer_id"])
    assert customer.business_profile.submission_event_id is None


def test_stale_analysis_after_resubmit_is_ignored(client, db_session, live_publisher):
    """REPROVADO → reenvio: a análise atrasada da 1ª submissão não vale para a 2ª."""
    client.put("/me/onboarding", json=_body(enviar=True))
    customer_id = client.get("/me").json()["customer_id"]
    customer = db_session.get(Customer, customer_id)
    customer.onboarding_status = "REPROVADO"
    db_session.commit()
    client.put("/me/onboarding", json=_body(enviar=True))
    first, second = _published_submissions(live_publisher)
    assert first["event_id"] != second["event_id"]

    stale = _event(customer_id, source_event_id=first["event_id"])
    assert handle_analysis_completed(db_session, stale) == "ignored"
    db_session.expire_all()
    assert customer.onboarding_status == "EM_ANALISE" and customer.business_profile.analise is None
    assert db_session.get(ProcessedEvent, stale["event_id"]).result == "ignored"

    current = _event(customer_id, source_event_id=second["event_id"], status="ANALISE_MANUAL")
    assert handle_analysis_completed(db_session, current) == "ok"
    db_session.expire_all()
    assert customer.onboarding_status == "ANALISE_MANUAL"


def test_analysis_without_source_event_id_keeps_old_behaviour(db_session):
    """Score antigo (sem source_event_id): aplica como antes."""
    customer = make_pj(db_session, submission_event_id="evt-atual")
    assert handle_analysis_completed(db_session, _event(customer.id)) == "ok"
    db_session.expire_all()
    assert customer.onboarding_status == "APROVADO"


def test_analysis_for_submission_without_stored_id_is_applied(db_session):
    """Envio feito antes deste deploy (sem submission_event_id gravado): não há com o que comparar."""
    customer = make_pj(db_session)
    assert handle_analysis_completed(db_session, _event(customer.id, source_event_id="evt-x")) == "ok"


def test_migration_adds_submission_event_id_column():
    assert ("ALTER TABLE business_profiles ADD COLUMN IF NOT EXISTS submission_event_id VARCHAR(36)"
            in migration_statements("postgresql"))
