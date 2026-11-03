import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import REGISTRY
from sqlalchemy.orm import sessionmaker

from app.messaging import consumer as consumer_module
from app.messaging.consumer import BINDINGS, Binding, EventConsumer, handle_message, process_body
from app.messaging.handlers import handle_analysis_completed
from app.models import ProcessedEvent
from tests.factories import make_pj

RK = "business.analysis_completed"


def _consumed(result):
    return REGISTRY.get_sample_value(
        "events_consumed_total", {"routing_key": RK, "result": result}
    ) or 0.0


def _event(customer_id, status="APROVADO", **extra):
    return {"event_id": str(uuid.uuid4()), "event_type": RK, "occurred_at": "2026-11-03T12:00:00+00:00",
            "customer_id": customer_id, "status": status, "score": 742.0,
            "faixa_risco": "MEDIO", "gerado_por": "llm+regras", **extra}


@pytest.mark.parametrize("status", ["APROVADO", "ANALISE_MANUAL"])
def test_analysis_completed_moves_em_analise(db_session, status):
    customer = make_pj(db_session, status="EM_ANALISE")
    event = _event(customer.id, status)
    assert handle_analysis_completed(db_session, event) == "ok"
    db_session.expire_all()
    assert customer.onboarding_status == status
    assert customer.business_profile.analise == {
        "score": 742.0, "faixa_risco": "MEDIO", "gerado_por": "llm+regras", "status": status,
    }
    assert db_session.get(ProcessedEvent, event["event_id"]).result == "ok"
    assert REGISTRY.get_sample_value("onboarding_manual_queue_size") == (status == "ANALISE_MANUAL")
    assert handle_analysis_completed(db_session, event) == "duplicate"


@pytest.mark.parametrize("status", ["RASCUNHO", "APROVADO", "REPROVADO", "ANALISE_MANUAL"])
def test_analysis_completed_ignored_outside_em_analise(db_session, status):
    customer = make_pj(db_session, status=status)
    assert handle_analysis_completed(db_session, _event(customer.id)) == "ignored"
    db_session.expire_all()
    assert customer.onboarding_status == status
    assert customer.business_profile.analise is None


def test_analysis_completed_unknown_customer_and_invalid(db_session):
    assert handle_analysis_completed(db_session, _event(9999)) == "ignored"
    assert handle_analysis_completed(db_session, _event(1, status="NEGADO")) == "invalid"
    assert handle_analysis_completed(db_session, {"customer_id": 1}) == "invalid"


def test_analysis_completed_creates_profile_when_missing(db_session):
    from app.models import Customer

    customer = Customer(nome="X", email="x@x.com", telefone="1", auth0_sub="s", tipo_pessoa="PJ",
                        onboarding_status="EM_ANALISE")
    db_session.add(customer)
    db_session.commit()
    assert handle_analysis_completed(db_session, _event(customer.id)) == "ok"
    db_session.expire_all()
    assert customer.business_profile.analise["status"] == "APROVADO"


def _factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_process_body_counts_results(engine, db_session):
    customer = make_pj(db_session)
    binding = BINDINGS[0]
    assert binding.queue == "onboarding.analysis-completed" and binding.routing_key == RK
    before_ok, before_invalid = _consumed("ok"), _consumed("invalid")
    assert process_body(json.dumps(_event(customer.id)).encode(), binding, _factory(engine)) == "ok"
    assert process_body(b"not json", binding, _factory(engine)) == "invalid"
    assert process_body(b"[1]", binding, _factory(engine)) == "invalid"
    assert _consumed("ok") == before_ok + 1
    assert _consumed("invalid") == before_invalid + 2


def test_process_body_error_rolls_back_and_raises(engine):
    def boom(db, payload):
        raise RuntimeError("db fora")

    before = _consumed("error")
    with pytest.raises(RuntimeError):
        process_body(b"{}", Binding("q", RK, boom), _factory(engine))
    assert _consumed("error") == before + 1


def _message(body, redelivered=False):
    return SimpleNamespace(body=body, redelivered=redelivered, ack=AsyncMock(), nack=AsyncMock())


@pytest.mark.parametrize("redelivered,requeue", [(False, True), (True, False)])
def test_handle_message_nacks_on_error(engine, redelivered, requeue):
    def boom(db, payload):
        raise RuntimeError("x")

    message = _message(b"{}", redelivered)
    asyncio.run(handle_message(message, Binding("q", RK, boom), _factory(engine)))
    message.nack.assert_awaited_once_with(requeue=requeue)
    message.ack.assert_not_awaited()


def test_handle_message_acks(engine):
    message = _message(b"{}")
    asyncio.run(handle_message(message, Binding("q", RK, lambda db, p: "ok"), _factory(engine)))
    message.ack.assert_awaited_once()


def test_consumer_without_url_is_noop():
    consumer = EventConsumer("", BINDINGS, MagicMock())
    consumer.start()
    assert consumer._task is None
    asyncio.run(consumer.stop())


def test_consumer_declares_durable_queue_without_arguments(monkeypatch, engine):
    queue = MagicMock()
    queue.bind = AsyncMock()
    queue.consume = AsyncMock()
    channel = MagicMock()
    channel.set_qos = AsyncMock()
    channel.declare_exchange = AsyncMock(return_value="exchange")
    channel.declare_queue = AsyncMock(return_value=queue)
    connection = MagicMock()
    connection.channel = AsyncMock(return_value=channel)
    connection.__aenter__ = AsyncMock(return_value=connection)
    connection.__aexit__ = AsyncMock(return_value=False)
    connect = AsyncMock(side_effect=[ConnectionError("down"), connection])
    monkeypatch.setattr(consumer_module.aio_pika, "connect_robust", connect)

    async def scenario():
        consumer = EventConsumer("amqp://localhost/", BINDINGS, _factory(engine), retry_delay=0)
        consumer.start()
        for _ in range(50):
            await asyncio.sleep(0)
            if queue.consume.await_count:
                break
        callback = queue.consume.await_args.args[0]
        message = _message(b"not json")
        await callback(message)
        message.ack.assert_awaited_once()
        await consumer.stop()
        assert consumer._task is None

    asyncio.run(scenario())
    assert connect.await_count == 2
    channel.declare_queue.assert_awaited_once_with("onboarding.analysis-completed", durable=True)
    queue.bind.assert_awaited_once_with("exchange", routing_key=RK)


def test_consumed_series_initialized_with_zero(client):
    body = client.get("/metrics").text
    for result in ("ok", "duplicate", "ignored", "invalid", "error"):
        assert f'events_consumed_total{{result="{result}",routing_key="{RK}"}} ' in body
    assert 'events_published_total{result="ok",routing_key="customer.onboarding_submitted"} ' in body
    assert 'events_published_total{result="error",routing_key="customer.onboarding_reviewed"} ' in body
