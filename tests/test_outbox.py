"""Outbox transacional: evento gravado no mesmo commit do status, caminho rápido e relay."""
import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import sessionmaker

from app.events import EventPublisher
from app.events.outbox import OutboxRelay, claim_statement, enqueue, publish_pending
from app.models import Customer, OutboxEvent
from app.schemas.onboarding import OnboardingIn
from app.services.onboarding_service import OnboardingService
from tests.factories import make_pj
from tests.test_onboarding import _body

SUBMITTED = "customer.onboarding_submitted"
REVIEWED = "customer.onboarding_reviewed"


def _published(routing_key, result="ok"):
    return REGISTRY.get_sample_value(
        "events_published_total", {"routing_key": routing_key, "result": result}
    ) or 0.0


def _rows(db):
    db.expire_all()
    return db.scalars(select(OutboxEvent).order_by(OutboxEvent.id)).all()


def _age(db, seconds=60):
    for row in _rows(db):
        row.created_at = datetime.utcnow() - timedelta(seconds=seconds)
    db.commit()


@pytest.fixture()
def factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture()
def use_publisher(client):
    original = client.app.state.publisher

    def _set(url="amqp://localhost/"):
        client.app.state.publisher = EventPublisher(url)

    yield _set
    client.app.state.publisher = original


def test_submit_writes_outbox_and_marks_published(client, db_session, broker, use_publisher):
    use_publisher()
    assert client.put("/me/onboarding", json=_body(enviar=True)).status_code == 200
    (row,) = _rows(db_session)
    event = json.loads(broker.exchange.publish.await_args.args[0].body)
    assert row.routing_key == SUBMITTED and row.event_id == event["event_id"] and row.payload == event
    assert row.published_at is not None and row.attempts == 1 and row.last_error is None
    customer = db_session.get(Customer, event["customer_id"])
    assert customer.business_profile.submission_event_id == row.event_id


def test_draft_does_not_write_outbox(client, db_session):
    assert client.put("/me/onboarding", json=_body()).status_code == 200
    assert _rows(db_session) == []


def test_broker_down_keeps_event_pending_then_relay_publishes(client, db_session, factory, broker, use_publisher):
    """RabbitMQ fora no envio: o status muda, o evento fica no outbox e o relay entrega depois."""
    broker.connect.side_effect = ConnectionError("broker fora")
    use_publisher()
    assert client.put("/me/onboarding", json=_body(enviar=True)).json()["onboarding_status"] == "EM_ANALISE"
    (row,) = _rows(db_session)
    assert row.published_at is None and row.attempts == 1 and "RabbitMQ" in row.last_error

    broker.connect.side_effect = None
    relay = OutboxRelay(EventPublisher("amqp://localhost/"), factory, min_age_seconds=5)
    assert asyncio.run(relay.relay_once()) == 0  # ainda recente: é a vez do caminho rápido
    _age(db_session)
    before = _published(SUBMITTED)
    assert asyncio.run(relay.relay_once()) == 1
    (row,) = _rows(db_session)
    assert row.published_at is not None and row.attempts == 2 and row.last_error is None
    sent = json.loads(broker.exchange.publish.await_args.args[0].body)
    assert sent["event_id"] == row.event_id  # mesmo event_id na republicação
    assert _published(SUBMITTED) == before + 1
    assert REGISTRY.get_sample_value("outbox_pending") == 0
    assert asyncio.run(relay.relay_once()) == 0  # nada pendente


def test_crash_before_publish_is_recovered_by_relay(db_session, factory, broker):
    """Processo morre entre o commit e o publish: o evento está no outbox e o relay o publica."""
    service = OnboardingService(db_session)
    service.save("auth0|crash", OnboardingIn(**_body(enviar=True)))
    (row,) = _rows(db_session)
    assert row.published_at is None and row.attempts == 0
    assert service.events == [(SUBMITTED, row.payload)]
    _age(db_session)
    assert asyncio.run(OutboxRelay(EventPublisher("amqp://x/"), factory).relay_once()) == 1
    assert _rows(db_session)[0].published_at is not None


def test_integrity_error_rolls_back_outbox(client, db_session, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import Session

    def boom(self):
        raise IntegrityError("insert", {}, Exception("unique"))

    monkeypatch.setattr(Session, "commit", boom)
    assert client.put("/me/onboarding", json=_body(enviar=True)).status_code == 409
    monkeypatch.undo()
    assert _rows(db_session) == []


def test_review_decision_writes_outbox(client, db_session, broker, use_publisher):
    customer = make_pj(db_session, status="ANALISE_MANUAL")
    broker.exchange.publish.side_effect = RuntimeError("canal fechado")
    use_publisher()
    response = client.post(f"/onboarding/reviews/{customer.id}/decision", json={"decisao": "APROVADO"})
    assert response.status_code == 200
    (row,) = _rows(db_session)
    assert row.routing_key == REVIEWED and row.payload["decisao"] == "APROVADO"
    assert row.published_at is None and row.attempts == 1 and "canal fechado" in row.last_error


def test_relay_batch_is_capped_and_stops_on_failure(db_session, factory):
    for i in range(5):
        enqueue(db_session, SUBMITTED, {"event_id": f"e{i}", "event_type": SUBMITTED})
    db_session.commit()
    _age(db_session)
    publisher = MagicMock(enabled=True, last_error=None)
    publisher.publish = AsyncMock(return_value=True)
    relay = OutboxRelay(publisher, factory, batch_size=2)
    assert asyncio.run(relay.relay_once()) == 2
    assert [c.args[1]["event_id"] for c in publisher.publish.await_args_list] == ["e0", "e1"]
    assert REGISTRY.get_sample_value("outbox_pending") == 3

    publisher.publish = AsyncMock(side_effect=[True, False])
    publisher.last_error = None  # sem motivo: usa o genérico
    relay.batch_size = 10
    assert asyncio.run(relay.relay_once()) == 1  # e2 ok, e3 falha, e4 fica para o próximo ciclo
    by_id = {r.event_id: r for r in _rows(db_session)}
    assert by_id["e2"].published_at is not None
    assert by_id["e3"].published_at is None and by_id["e3"].attempts == 1
    assert by_id["e3"].last_error == "falha ao publicar"
    assert by_id["e4"].attempts == 0
    assert REGISTRY.get_sample_value("outbox_pending") == 2


def test_disabled_messaging_marks_as_published(db_session, factory):
    """Sem RABBITMQ_URL não há broker para tentar de novo: o caminho rápido marca como publicado."""
    enqueue(db_session, SUBMITTED, {"event_id": "off", "event_type": SUBMITTED})
    db_session.commit()
    asyncio.run(publish_pending(EventPublisher(""), factory, SUBMITTED, {"event_id": "off"}))
    assert _rows(db_session)[0].published_at is not None


def test_publish_pending_swallows_db_errors(caplog):
    publisher = MagicMock(last_error=None)
    publisher.publish = AsyncMock(return_value=True)

    def broken_factory():
        raise RuntimeError("pool esgotado")

    asyncio.run(publish_pending(publisher, broken_factory, SUBMITTED, {"event_id": "x"}))
    assert "relay cuida" in caplog.text


def test_claim_uses_skip_locked_on_postgres_only():
    stmt = claim_statement(datetime(2026, 11, 3), 50)
    assert "FOR UPDATE SKIP LOCKED" in str(stmt.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" not in str(stmt.compile(dialect=sqlite.dialect()))


def test_relay_not_started_without_broker():
    async def scenario():
        relay = OutboxRelay(EventPublisher(""), MagicMock())
        relay.start()
        assert relay._task is None
        await relay.stop()

    asyncio.run(scenario())


def test_relay_loop_survives_errors_and_stops():
    calls = []

    async def scenario():
        relay = OutboxRelay(MagicMock(enabled=True), MagicMock(), poll_seconds=0.001)

        async def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("banco fora")
            return 0

        relay.relay_once = flaky
        relay.start()
        relay.start()  # idempotente
        for _ in range(200):
            await asyncio.sleep(0.001)
            if len(calls) >= 3:
                break
        await relay.stop()
        assert relay._task is None

    asyncio.run(scenario())
    assert len(calls) >= 3


def test_lifespan_starts_and_stops_relay(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    relay = MagicMock()
    relay.stop = AsyncMock()
    monkeypatch.setattr(app.state, "outbox_relay", relay)
    with TestClient(app):
        relay.start.assert_called_once()
    relay.stop.assert_awaited_once()


def test_outbox_pending_metric_exposed(client):
    assert "outbox_pending " in client.get("/metrics").text


def test_relay_poll_seconds_from_settings():
    from app.config.settings import Settings, settings
    from app.main import app

    assert Settings.model_fields["outbox_poll_seconds"].default == 10
    assert app.state.outbox_relay.poll_seconds == settings.outbox_poll_seconds
