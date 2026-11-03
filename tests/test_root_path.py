from fastapi.testclient import TestClient

from app.core.security import Principal, require_auth
from app.main import app


def _client(root_path=""):
    app.dependency_overrides[require_auth] = lambda: Principal("t", "auth0|t", frozenset())
    return TestClient(app, root_path=root_path)


def test_docs_use_root_path_prefix():
    try:
        with _client("/onboarding") as c:
            docs = c.get("/docs")
            assert docs.status_code == 200
            assert "/onboarding/openapi.json" in docs.text
            redoc = c.get("/redoc")
            assert "/onboarding/openapi.json" in redoc.text
            schema = c.get("/openapi.json").json()
            assert schema["servers"] == [{"url": "/onboarding"}]
            assert "/customers" in schema["paths"]
    finally:
        app.dependency_overrides.clear()


def test_docs_without_root_path():
    try:
        with _client() as c:
            assert '"/openapi.json"' in c.get("/docs").text or "'/openapi.json'" in c.get("/docs").text
            assert "servers" not in c.get("/openapi.json").json()
    finally:
        app.dependency_overrides.clear()
