import json
import logging
import sys
import uuid

import pytest

from app.core.logging import JsonFormatter, configure_logging, request_id_var


def _access_records(caplog):
    return [r for r in caplog.records if r.name == "app.access"]


def test_request_id_is_generated_and_logged(client, caplog):
    caplog.set_level(logging.INFO, logger="app.access")
    response = client.get("/health")
    request_id = response.headers["X-Request-ID"]
    uuid.UUID(request_id)

    line = json.loads(JsonFormatter().format(_access_records(caplog)[-1]))
    assert line["message"] == "request"
    assert line["method"] == "GET"
    assert line["path"] == "/health"
    assert line["status"] == 200
    assert line["duration_ms"] >= 0
    assert line["level"] == "INFO"


def test_incoming_request_id_is_echoed(client, caplog):
    caplog.set_level(logging.INFO, logger="app.access")
    response = client.get("/customers/999", headers={"X-Request-ID": "gw-123"})
    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "gw-123"
    assert _access_records(caplog)[-1].status == 404


def test_formatter_includes_request_id_and_exception():
    token = request_id_var.set("abc-1")
    try:
        try:
            raise ValueError("boom")
        except ValueError:
            record = logging.getLogger("t").makeRecord(
                "t", logging.ERROR, __file__, 1, "falhou %s", ("x",), sys.exc_info(),
            )
        line = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert line["request_id"] == "abc-1"
    assert line["message"] == "falhou x"
    assert "ValueError: boom" in line["exc_info"]


def test_configure_logging_is_idempotent():
    root = logging.getLogger()
    configure_logging("info")
    configure_logging("DEBUG")
    json_handlers = [h for h in root.handlers if getattr(h, "_erp_json", False)]
    assert len(json_handlers) == 1
    assert root.level == logging.DEBUG
    configure_logging("INFO")


@pytest.mark.parametrize("scope_type", ["lifespan"])
def test_non_http_scope_passes_through(scope_type):
    import asyncio

    from app.core.logging import RequestIDMiddleware

    called = {}

    async def inner(scope, receive, send):
        called["scope"] = scope["type"]

    asyncio.run(RequestIDMiddleware(inner)({"type": scope_type}, None, None))
    assert called["scope"] == scope_type
