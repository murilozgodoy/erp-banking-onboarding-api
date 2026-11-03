from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html

from app import models  # noqa: F401
from app.config.database import Base, engine
from app.config.migrations import run_migrations
from app.config.settings import settings
from app.core.logging import RequestIDMiddleware, configure_logging
from app.core.metrics import setup_metrics
from app.core.security import require_auth
from app.events import EventPublisher
from app.routers import customers, health, me, templates


def _openapi_url(request: Request) -> str:
    """openapi.json URL including the gateway prefix (ROOT_PATH), e.g. /onboarding/openapi.json."""
    return request.scope.get("root_path", "").rstrip("/") + "/openapi.json"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await app.state.publisher.connect()
    try:
        yield
    finally:
        await app.state.publisher.close()


def create_app() -> FastAPI:
    configure_logging(settings.log_level)
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)

    app = FastAPI(
        title="ErpIa - Onboarding API",
        version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None,
        description="ErpIa: cadastro de clientes, anamnese financeira e onboarding PJ do portal",
        root_path=settings.root_path,
        lifespan=lifespan,
    )
    app.state.publisher = EventPublisher(settings.rabbitmq_url)

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
    app.include_router(templates.router, dependencies=[Depends(require_auth)])

    @app.get("/openapi.json", dependencies=[Depends(require_auth)], include_in_schema=False)
    def openapi(request: Request):
        schema = dict(app.openapi())
        root_path = request.scope.get("root_path", "").rstrip("/")
        if root_path:
            schema["servers"] = [{"url": root_path}]
        return schema

    @app.get("/docs", dependencies=[Depends(require_auth)], include_in_schema=False)
    def docs(request: Request):
        return get_swagger_ui_html(openapi_url=_openapi_url(request), title=app.title)

    @app.get("/redoc", dependencies=[Depends(require_auth)], include_in_schema=False)
    def redoc(request: Request):
        return get_redoc_html(openapi_url=_openapi_url(request), title=app.title)

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=True)
