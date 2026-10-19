from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html

from app.core.security import require_auth
from app.config.settings import settings

from app import models  # noqa: F401
from app.config.database import Base, engine
from app.routers import customers, health


def create_app() -> FastAPI:
    Base.metadata.create_all(bind=engine)

    app = FastAPI(
        title="ERP Banking - Onboarding API",
        version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None,
        description="Cadastro de clientes e anamnese financeira",
    )
    app.include_router(health.router)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(customers.router, dependencies=[Depends(require_auth)])

    @app.get("/openapi.json", dependencies=[Depends(require_auth)], include_in_schema=False)
    def openapi():
        return app.openapi()

    @app.get("/docs", dependencies=[Depends(require_auth)], include_in_schema=False)
    def docs():
        return get_swagger_ui_html(openapi_url="/openapi.json", title=app.title)

    @app.get("/redoc", dependencies=[Depends(require_auth)], include_in_schema=False)
    def redoc():
        return get_redoc_html(openapi_url="/openapi.json", title=app.title)

    return app


app = create_app()
