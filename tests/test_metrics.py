from prometheus_client import REGISTRY

from app.main import create_app


def _value(name, labels=None):
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


def test_metrics_endpoint_is_public_and_has_http_metrics(client):
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body
    assert 'handler="/health"' in body
    assert "customers_created_total" in body


def test_metrics_not_in_openapi_schema(client):
    assert "/metrics" not in client.app.openapi()["paths"]


def test_customers_created_counter_increments(client, sample_customer_payload):
    before = _value("customers_created_total")
    assert client.post("/customers", json=sample_customer_payload).status_code == 201
    assert client.post("/customers", json=sample_customer_payload).status_code == 409
    assert _value("customers_created_total") == before + 1


def test_create_app_twice_does_not_duplicate_metrics():
    create_app()
    create_app()


def test_events_published_series_initialized_with_zero(client):
    from app.core.metrics import init_metrics

    init_metrics()  # idempotente
    body = client.get("/metrics").text
    assert 'events_published_total{result="error",routing_key="customer.created"} ' in body
    assert 'events_published_total{result="ok",routing_key="customer.anamnesis_updated"} ' in body
