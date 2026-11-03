"""ROOT_PATH só afeta o OpenAPI/Swagger, nunca o roteamento.

Bug de produção: com FastAPI(root_path="/onboarding"), o Starlette tirava o prefixo de rotas que começam com
/onboarding (/onboarding/templates, /onboarding/reviews) e respondia 404 dentro do container.
"""
import pytest
from fastapi.testclient import TestClient

from sqlalchemy.orm import sessionmaker

from app.config.database import get_db
from app.config.settings import settings
from app.core.security import Principal, require_auth
from app.main import create_app


@pytest.fixture
def client_with_prefix(monkeypatch, engine):
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        session = testing_session()
        try:
            yield session
        finally:
            session.close()

    def make(prefix: str):
        monkeypatch.setattr(settings, "root_path", prefix)
        app = create_app()
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[require_auth] = lambda: Principal(
            "t", "auth0|t", frozenset({"review:onboarding", "read:self", "read:customers"})
        )
        return TestClient(app)

    return make


def test_routes_that_start_with_the_prefix_still_resolve(client_with_prefix):
    with client_with_prefix("/onboarding") as c:
        templates = c.get("/onboarding/templates")
        assert templates.status_code == 200
        assert any(t["segmento"] == "varejo" for t in templates.json())
        assert c.get("/onboarding/reviews").status_code == 200
        assert c.get("/health").status_code == 200


def test_docs_use_root_path_prefix(client_with_prefix):
    with client_with_prefix("/onboarding/") as c:
        docs = c.get("/docs")
        assert docs.status_code == 200
        assert "/onboarding/openapi.json" in docs.text
        assert "/onboarding/openapi.json" in c.get("/redoc").text
        schema = c.get("/openapi.json").json()
        assert schema["servers"] == [{"url": "/onboarding"}]
        assert "/onboarding/templates" in schema["paths"]
        assert "/customers" in schema["paths"]


def test_docs_without_root_path(client_with_prefix):
    with client_with_prefix("") as c:
        text = c.get("/docs").text
        assert '"/openapi.json"' in text or "'/openapi.json'" in text
        assert "servers" not in c.get("/openapi.json").json()
