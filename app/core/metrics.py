"""Prometheus metrics: default HTTP metrics (instrumentator) + business counters.

Counters live at module level so they are registered once, even when the app is
created several times (tests).
"""
from fastapi import FastAPI
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator

CUSTOMERS_CREATED = Counter(
    "customers_created_total",
    "Clientes criados com sucesso via POST /customers",
)

EVENTS_PUBLISHED = Counter(
    "events_published_total",
    "Eventos publicados no RabbitMQ (exchange erp.events)",
    ["routing_key", "result"],
)


def setup_metrics(app: FastAPI) -> None:
    """Instrument HTTP requests and expose a public GET /metrics (no auth)."""
    Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(
        app, endpoint="/metrics", include_in_schema=False
    )
