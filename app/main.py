import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html

from app import models  # noqa: F401
from app.config.database import Base, SessionLocal, engine
from app.config.migrations import run_migrations
from app.config.settings import settings
from app.core.errors import ApiError, api_error_handler, validation_error_handler
from app.core.logging import RequestIDMiddleware, configure_logging
from app.core.metrics import setup_metrics
from app.core.security import require_auth
from app.events import EventPublisher
from app.events.outbox import OutboxRelay
from app.messaging.consumer import BINDINGS, EventConsumer
from app.routers import customers, health, me, reviews, team, templates
from app.services.onboarding_service import refresh_manual_queue
from app.team.members import refresh_team_members

logger = logging.getLogger(__name__)


def _prefix() -> str:
    """Prefixo do gateway (ROOT_PATH), usado SÓ no OpenAPI/Swagger.

    Não vai para FastAPI(root_path=...): o Starlette remove o root_path do início do caminho ao rotear,
    e as rotas /onboarding/templates e /onboarding/reviews começam com o mesmo texto que o prefixo
    /onboarding, então davam 404 dentro do container.
    """
    return settings.root_path.rstrip("/")


def _openapi_url() -> str:
    """openapi.json com o prefixo do gateway, ex.: /onboarding/openapi.json."""
    return _prefix() + "/openapi.json"


def _init_manual_queue_gauge() -> None:
    """onboarding_manual_queue_size a partir do banco no startup; falha só é logada."""
    try:
        with SessionLocal() as db:
            refresh_manual_queue(db)
    except Exception:
        logger.exception("Falha ao inicializar onboarding_manual_queue_size")


def _init_team_gauge() -> None:
    """team_members_total a partir do banco no startup; falha só é logada."""
    try:
        with SessionLocal() as db:
            refresh_team_members(db)
    except Exception:
        logger.exception("Falha ao inicializar team_members_total")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_manual_queue_gauge()
    _init_team_gauge()
    await app.state.publisher.connect()
    app.state.consumer.start()
    app.state.outbox_relay.start()
    try:
        yield
    finally:
        await app.state.outbox_relay.stop()
        await app.state.consumer.stop()
        await app.state.publisher.close()


def create_app() -> FastAPI:
    configure_logging(settings.log_level)
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)

    app = FastAPI(
        title="ErpIa - Onboarding API",
        version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None,
        description="ErpIa: cadastro de clientes, anamnese financeira e onboarding PJ do portal",
        lifespan=lifespan,
    )
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.state.publisher = EventPublisher(settings.rabbitmq_url)
    app.state.consumer = EventConsumer(settings.rabbitmq_url, BINDINGS, SessionLocal)
    app.state.outbox_relay = OutboxRelay(app.state.publisher, SessionLocal, settings.outbox_poll_seconds)

    app.include_router(health.router)
    setup_metrics(app)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestIDMiddleware)  # mais externo: cobre CORS, auth e erros
    app.include_router(customers.router, dependencies=[Depends(require_auth)])
    app.include_router(me.router, dependencies=[Depends(require_auth)])
    app.include_router(team.router, dependencies=[Depends(require_auth)])
    app.include_router(templates.router, dependencies=[Depends(require_auth)])
    app.include_router(reviews.router, dependencies=[Depends(require_auth)])

    @app.get("/openapi.json", dependencies=[Depends(require_auth)], include_in_schema=False)
    def openapi():
        schema = dict(app.openapi())
        if _prefix():
            schema["servers"] = [{"url": _prefix()}]
        return schema

    @app.get("/docs", dependencies=[Depends(require_auth)], include_in_schema=False)
    def docs():
        return get_swagger_ui_html(openapi_url=_openapi_url(), title=app.title)

    @app.get("/redoc", dependencies=[Depends(require_auth)], include_in_schema=False)
    def redoc():
        return get_redoc_html(openapi_url=_openapi_url(), title=app.title)

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=True)
