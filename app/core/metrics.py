"""Prometheus metrics: default HTTP metrics (instrumentator) + business counters.

Counters live at module level so they are registered once, even when the app is
created several times (tests).
"""
from fastapi import FastAPI
from prometheus_client import Counter
from prometheus_fastapi_instrumentator import Instrumentator

from app.templates import SEGMENTOS

CUSTOMERS_CREATED = Counter(
    "customers_created_total",
    "Clientes criados com sucesso via POST /customers",
)

EVENTS_PUBLISHED = Counter(
    "events_published_total",
    "Eventos publicados no RabbitMQ (exchange erp.events)",
    ["routing_key", "result"],
)

ONBOARDING_SUBMISSIONS = Counter(
    "onboarding_submissions_total",
    "Onboardings PJ enviados para análise (PUT /me/onboarding com enviar=true)",
    ["segmento"],
)

ONBOARDING_DRAFTS = Counter(
    "onboarding_drafts_saved_total",
    "Rascunhos de onboarding PJ salvos (PUT /me/onboarding com enviar=false)",
)

PUBLISHED_ROUTING_KEYS = (
    "customer.created",
    "customer.anamnesis_updated",
    "customer.onboarding_submitted",
)
PUBLISHED_RESULTS = ("ok", "error")


def init_metrics() -> None:
    """Cria as series rotuladas com valor 0 (evita "No data" no Grafana). Idempotente."""
    for routing_key in PUBLISHED_ROUTING_KEYS:
        for result in PUBLISHED_RESULTS:
            EVENTS_PUBLISHED.labels(routing_key=routing_key, result=result)
    for segmento in SEGMENTOS:
        ONBOARDING_SUBMISSIONS.labels(segmento=segmento)


init_metrics()


def setup_metrics(app: FastAPI) -> None:
    """Instrument HTTP requests and expose a public GET /metrics (no auth)."""
    Instrumentator(excluded_handlers=["/metrics"]).instrument(app).expose(
        app, endpoint="/metrics", include_in_schema=False
    )
