from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config.database import Base, get_db
from app.main import app
from app.core.security import Principal, require_auth
from app.events import publisher as publisher_module

ALL_PERMISSIONS = frozenset({
    "read:customers", "write:customers", "read:self", "write:self", "review:onboarding",
})


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session(engine):
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(engine):
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_auth] = lambda: Principal(
        token="test-token", subject="auth0|test", permissions=ALL_PERMISSIONS
    )
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def sample_customer_payload():
    return {
        "nome": "João da Silva",
        "cpf": "12345678900",
        "email": "joao@example.com",
        "telefone": "11999998888",
        "address": {
            "rua": "Rua das Flores",
            "numero": "123",
            "cidade": "São Paulo",
            "estado": "SP",
            "cep": "01234567",
        },
        "financial_profile": {
            "renda_mensal": 8000.0,
            "patrimonio": 50000.0,
            "ocupacao": "CLT",
        },
    }


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
