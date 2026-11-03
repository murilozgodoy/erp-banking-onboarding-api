"""RabbitMQ publisher (aio-pika) for the onboarding domain events.

Empty RABBITMQ_URL = messaging disabled (no-op, no metric). A publish failure never
propagates: it is logged and counted as events_published_total{result="error"}.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import aio_pika
from fastapi import Request

from app.core.metrics import EVENTS_PUBLISHED

logger = logging.getLogger(__name__)

EXCHANGE_NAME = "erp.events"
CUSTOMER_CREATED = "customer.created"
ANAMNESIS_UPDATED = "customer.anamnesis_updated"


def _envelope(event_type: str, **payload: Any) -> dict[str, Any]:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }


def customer_created_event(customer) -> dict[str, Any]:
    return _envelope(
        CUSTOMER_CREATED,
        customer_id=customer.id,
        nome=customer.nome,
        cpf=customer.cpf,
        email=customer.email,
    )


def anamnesis_updated_event(customer_id: int, anamnesis) -> dict[str, Any]:
    return _envelope(
        ANAMNESIS_UPDATED,
        customer_id=customer_id,
        dividas_ativas=anamnesis.dividas_ativas,
        comprometimento_renda=anamnesis.comprometimento_renda,
    )


class EventPublisher:
    def __init__(self, url: str) -> None:
        self.url = url
        self._connection = None
        self._channel = None
        self._exchange = None
        # Serializa connect/close: sem isso, publishes concorrentes após uma falha no startup
        # abririam várias conexões e algumas ficariam penduradas.
        self._lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    async def connect(self) -> None:
        """Connect and declare the exchange; on failure log and retry lazily on publish."""
        if not self.enabled or self._exchange is not None:
            return
        async with self._lock:
            if self._exchange is not None:  # double-checked: outra task já conectou
                return
            try:
                self._connection = await aio_pika.connect_robust(self.url)
                self._channel = await self._connection.channel()
                self._exchange = await self._channel.declare_exchange(
                    EXCHANGE_NAME, aio_pika.ExchangeType.TOPIC, durable=True
                )
                logger.info("Conectado ao RabbitMQ (exchange %s)", EXCHANGE_NAME)
            except Exception:
                logger.exception("Falha ao conectar no RabbitMQ; nova tentativa no próximo publish")
                await self._close_unlocked()

    async def close(self) -> None:
        """Fecha a conexão; idempotente (pode ser chamado várias vezes, inclusive sem conexão)."""
        async with self._lock:
            await self._close_unlocked()

    async def _close_unlocked(self) -> None:
        connection = self._connection
        self._connection = self._channel = self._exchange = None
        if connection is not None:
            try:
                await connection.close()
            except Exception:
                logger.exception("Falha ao fechar conexão com o RabbitMQ")

    async def publish(self, routing_key: str, payload: dict[str, Any]) -> None:
        """Publish a JSON event. Never raises."""
        if not self.enabled:
            return
        try:
            await self.connect()
            if self._exchange is None:
                raise RuntimeError("RabbitMQ indisponível")
            message = aio_pika.Message(
                body=json.dumps(payload, default=str).encode(),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                message_id=payload.get("event_id"),
                type=payload.get("event_type"),
            )
            await self._exchange.publish(message, routing_key=routing_key)
        except Exception:
            logger.exception("Falha ao publicar evento %s", routing_key)
            EVENTS_PUBLISHED.labels(routing_key=routing_key, result="error").inc()
            return
        EVENTS_PUBLISHED.labels(routing_key=routing_key, result="ok").inc()


def get_publisher(request: Request) -> EventPublisher:
    return request.app.state.publisher
