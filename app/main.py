from fastapi import FastAPI

from app.database import Base, engine
from app.routers import customers, health


def create_app() -> FastAPI:
    Base.metadata.create_all(bind=engine)

    app = FastAPI(
        title="ERP Banking - Onboarding API",
        version="1.0.0",
        description="Cadastro de clientes e anamnese financeira",
    )
    app.include_router(health.router)
    app.include_router(customers.router)
    return app


app = create_app()
