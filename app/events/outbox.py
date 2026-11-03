"""Outbox transacional dos eventos do onboarding.

1. `enqueue` grava o evento em `outbox_events` na MESMA transação da mudança de status.
2. Depois do commit, `publish_pending` (BackgroundTasks) publica na hora (caminho rápido) e marca
   `published_at`.
3. Se o broker estava fora ou o processo morreu antes do publish, o `OutboxRelay` (task do lifespan)
   republica a cada `OUTBOX_POLL_SECONDS` as linhas não publicadas com mais de `min_age_seconds`, em lotes
   limitados, incrementando `attempts` e guardando `last_error`.

O `event_id` é sempre o do payload gravado: uma republicação duplicada é segura (os consumidores são
idempotentes por `event_id`). As idas ao banco são curtas e fora do publish (pool pequeno): o relay não
segura conexão enquanto fala com o RabbitMQ nem entre ciclos.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.metrics import OUTBOX_PENDING
from app.models import OutboxEvent

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]
FALLBACK_ERROR = "falha ao publicar"


def enqueue(db: Session, routing_key: str, payload: dict[str, Any]) -> None:
    """Adiciona o evento à transação corrente (o commit é de quem chama)."""
    db.add(OutboxEvent(event_id=payload["event_id"], routing_key=routing_key, payload=payload))


def session_factory_for(db: Session) -> SessionFactory:
    """Sessões novas no mesmo engine da requisição (a sessão da requisição já foi fechada)."""
    return sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)


def claim_statement(cutoff: datetime, batch_size: int):
    return (
        select(OutboxEvent.event_id, OutboxEvent.routing_key, OutboxEvent.payload)
        .where(OutboxEvent.published_at.is_(None), OutboxEvent.created_at <= cutoff)
        .order_by(OutboxEvent.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )


def _claim(session_factory: SessionFactory, min_age_seconds: float, batch_size: int) -> list[tuple]:
    """Lote de pendentes mais antigos que `min_age_seconds` (o caminho rápido já teve sua chance).

    FOR UPDATE SKIP LOCKED no PostgreSQL (outro relay concorrente pula as linhas em vez de esperar);
    o SQLite ignora a cláusula. A transação termina aqui: nada fica preso durante o publish.
    """
    cutoff = datetime.utcnow() - timedelta(seconds=min_age_seconds)
    with session_factory() as db:
        rows = db.execute(claim_statement(cutoff, batch_size)).all()
        db.commit()
    return [tuple(row) for row in rows]


def _record(session_factory: SessionFactory, published: list[str], failed: dict[str, str]) -> None:
    """Uma tentativa a mais em cada linha; marca `published_at` ou guarda `last_error`."""
    if not published and not failed:
        return
    now = datetime.utcnow()
    with session_factory() as db:
        if published:
            db.execute(
                update(OutboxEvent)
                .where(OutboxEvent.event_id.in_(published), OutboxEvent.published_at.is_(None))
                .values(published_at=now, attempts=OutboxEvent.attempts + 1, last_error=None)
                .execution_options(synchronize_session=False)
            )
        for event_id, error in failed.items():
            db.execute(
                update(OutboxEvent)
                .where(OutboxEvent.event_id == event_id, OutboxEvent.published_at.is_(None))
                .values(attempts=OutboxEvent.attempts + 1, last_error=error)
                .execution_options(synchronize_session=False)
            )
        db.commit()


def _pending_count(session_factory: SessionFactory) -> int:
    with session_factory() as db:
        return db.scalar(
            select(func.count()).select_from(OutboxEvent).where(OutboxEvent.published_at.is_(None))
        ) or 0


async def _publish(publisher, event_id: str, routing_key: str, payload: dict) -> str | None:
    """None = publicado; senão o motivo da falha."""
    if await publisher.publish(routing_key, payload):
        return None
    return publisher.last_error or FALLBACK_ERROR


async def publish_pending(publisher, session_factory: SessionFactory, routing_key: str, payload: dict) -> None:
    """Caminho rápido (BackgroundTasks): publica logo após o commit e marca o resultado.

    Nunca levanta: se o publish ou a marcação falharem, o relay republica depois.
    """
    event_id = payload["event_id"]
    error = await _publish(publisher, event_id, routing_key, payload)
    try:
        await asyncio.to_thread(
            _record, session_factory, [] if error else [event_id], {event_id: error} if error else {}
        )
    except Exception:
        logger.exception("Falha ao marcar o outbox do evento %s; o relay cuida", event_id)


class OutboxRelay:
    """Task de fundo que republica o que ficou pendente no outbox."""

    def __init__(
        self,
        publisher,
        session_factory: SessionFactory,
        poll_seconds: float = 10,
        min_age_seconds: float = 5,
        batch_size: int = 50,
    ) -> None:
        self.publisher = publisher
        self.session_factory = session_factory
        self.poll_seconds = poll_seconds
        self.min_age_seconds = min_age_seconds
        self.batch_size = batch_size
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Sem RABBITMQ_URL não há para onde republicar: não inicia."""
        if not self.publisher.enabled or self.poll_seconds <= 0 or self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="outbox-relay")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        while True:
            try:
                await self.relay_once()
            except Exception:
                logger.exception("Falha no ciclo do relay do outbox")
            await asyncio.sleep(self.poll_seconds)

    async def relay_once(self) -> int:
        """Um ciclo: republica um lote e atualiza o gauge `outbox_pending`. Devolve quantos publicou."""
        claimed = await asyncio.to_thread(_claim, self.session_factory, self.min_age_seconds, self.batch_size)
        published: list[str] = []
        failed: dict[str, str] = {}
        for event_id, routing_key, payload in claimed:
            error = await _publish(self.publisher, event_id, routing_key, payload)
            if error:
                failed[event_id] = error
                break  # broker fora: o resto do lote fica para o próximo ciclo
            published.append(event_id)
        await asyncio.to_thread(_record, self.session_factory, published, failed)
        if published or failed:
            logger.info("Relay do outbox: %d republicados, %d falhas", len(published), len(failed))
        OUTBOX_PENDING.set(await asyncio.to_thread(_pending_count, self.session_factory))
        return len(published)
