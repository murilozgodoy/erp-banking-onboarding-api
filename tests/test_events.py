import asyncio
import json
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import aio_pika
import pytest
from prometheus_client import REGISTRY

from app.events import publisher as publisher_module
from app.events import (
    EXCHANGE_NAME,
    EventPublisher,
    anamnesis_updated_event,
    customer_created_event,
)


def _count(routing_key, result):
    return REGISTRY.get_sample_value(
        "events_published_total", {"routing_key": routing_key, "result": result}
    ) or 0.0


@pytest.fixture()
def broker(monkeypatch):
    exchange = MagicMock()
    exchange.publish = AsyncMock()
    channel = MagicMock()
    channel.declare_exchange = AsyncMock(return_value=exchange)
    connection = MagicMock()
    connection.channel = AsyncMock(return_value=channel)
    connection.close = AsyncMock()
    connect = AsyncMock(return_value=connection)
    monkeypatch.setattr(publisher_module.aio_pika, "connect_robust", connect)
    return SimpleNamespace(connect=connect, connection=connection, channel=channel, exchange=exchange)


def test_customer_created_event_payload():
    customer = SimpleNamespace(id=7, nome="Ana", cpf="12345678900", email="ana@example.com")
    event = customer_created_event(customer)
    uuid.UUID(event["event_id"])
    assert event["event_type"] == "customer.created"
    assert datetime.fromisoformat(event["occurred_at"]).utcoffset().total_seconds() == 0
    assert event | {"event_id": None, "occurred_at": None} == {
        "event_id": None, "occurred_at": None, "event_type": "customer.created",
        "customer_id": 7, "nome": "Ana", "cpf": "12345678900", "email": "ana@example.com",
    }


def test_anamnesis_updated_event_payload():
    anamnesis = SimpleNamespace(dividas_ativas=1500.0, comprometimento_renda=30.0)
    event = anamnesis_updated_event(7, anamnesis)
    assert event["event_type"] == "customer.anamnesis_updated"
    assert event["customer_id"] == 7
    assert event["dividas_ativas"] == 1500.0
    assert event["comprometimento_renda"] == 30.0


def test_disabled_publisher_is_noop(broker):
    pub = EventPublisher("")
    assert not pub.enabled
    before_ok = _count("customer.created", "ok")
    before_err = _count("customer.created", "error")
    asyncio.run(pub.connect())
    asyncio.run(pub.publish("customer.created", {"event_id": "x"}))
    asyncio.run(pub.close())
    broker.connect.assert_not_awaited()
    assert _count("customer.created", "ok") == before_ok
    assert _count("customer.created", "error") == before_err


def test_publish_sends_persistent_json_to_topic_exchange(broker):
    pub = EventPublisher("amqp://guest:guest@localhost/")
    before = _count("customer.created", "ok")

    async def scenario():
        await pub.connect()
        await pub.publish("customer.created", {"event_id": "abc", "event_type": "customer.created"})
        await pub.close()

    asyncio.run(scenario())

    broker.connect.assert_awaited_once_with("amqp://guest:guest@localhost/")
    broker.channel.declare_exchange.assert_awaited_once_with(
        EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
    )
    message = broker.exchange.publish.await_args.args[0]
    assert broker.exchange.publish.await_args.kwargs == {"routing_key": "customer.created"}
    assert json.loads(message.body) == {"event_id": "abc", "event_type": "customer.created"}
    assert message.content_type == "application/json"
    assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
    broker.connection.close.assert_awaited_once()
    assert _count("customer.created", "ok") == before + 1


def test_publish_error_is_swallowed_and_counted(broker):
    broker.exchange.publish.side_effect = RuntimeError("canal fechado")
    pub = EventPublisher("amqp://localhost/")
    before = _count("customer.anamnesis_updated", "error")
    asyncio.run(pub.publish("customer.anamnesis_updated", {"event_id": "abc"}))
    assert _count("customer.anamnesis_updated", "error") == before + 1


def test_connect_failure_is_logged_and_retried_lazily(broker):
    broker.connect.side_effect = [ConnectionError("broker fora"), broker.connection]
    pub = EventPublisher("amqp://localhost/")
    before_err = _count("customer.created", "error")
    before_ok = _count("customer.created", "ok")

    async def scenario():
        await pub.connect()  # falha, não propaga
        await pub.publish("customer.created", {"event_id": "1"})  # reconecta e publica

    asyncio.run(scenario())
    assert broker.connect.await_count == 2
    assert _count("customer.created", "ok") == before_ok + 1
    assert _count("customer.created", "error") == before_err


def test_publish_when_broker_still_down_counts_error(broker):
    broker.connect.side_effect = ConnectionError("broker fora")
    pub = EventPublisher("amqp://localhost/")
    before = _count("customer.created", "error")
    asyncio.run(pub.publish("customer.created", {"event_id": "1"}))
    assert _count("customer.created", "error") == before + 1


def test_close_errors_are_swallowed(broker):
    broker.connection.close.side_effect = RuntimeError("já fechada")
    pub = EventPublisher("amqp://localhost/")

    async def scenario():
        await pub.connect()
        await pub.close()

    asyncio.run(scenario())


def test_api_publishes_customer_events(client, sample_customer_payload, broker):
    original = client.app.state.publisher
    client.app.state.publisher = EventPublisher("amqp://localhost/")
    try:
        created = client.post("/customers", json=sample_customer_payload)
        assert created.status_code == 201
        customer_id = created.json()["id"]
        updated = client.put(
            f"/customers/{customer_id}/anamnesis",
            json={"dividas_ativas": 1000.0, "comprometimento_renda": 25.0},
        )
        assert updated.status_code == 200
    finally:
        client.app.state.publisher = original

    calls = broker.exchange.publish.await_args_list
    assert [c.kwargs["routing_key"] for c in calls] == [
        "customer.created", "customer.anamnesis_updated",
    ]
    created_event = json.loads(calls[0].args[0].body)
    assert created_event["customer_id"] == customer_id
    assert created_event["cpf"] == sample_customer_payload["cpf"]
    anamnesis_event = json.loads(calls[1].args[0].body)
    assert anamnesis_event["dividas_ativas"] == 1000.0
    assert anamnesis_event["comprometimento_renda"] == 25.0


def test_api_request_succeeds_when_broker_is_down(client, sample_customer_payload, broker):
    broker.connect.side_effect = ConnectionError("broker fora")
    original = client.app.state.publisher
    client.app.state.publisher = EventPublisher("amqp://localhost/")
    before = _count("customer.created", "error")
    try:
        assert client.post("/customers", json=sample_customer_payload).status_code == 201
    finally:
        client.app.state.publisher = original
    assert _count("customer.created", "error") == before + 1
