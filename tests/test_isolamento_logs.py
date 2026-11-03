"""Revisão de segurança: nada de token, CNPJ/CPF completo, e-mail ou payload de evento nos logs."""
import logging

import pytest

from app.core.logging import JsonFormatter, safe_path
from app.core.security import Principal, require_auth
from app.main import app
from app.messaging.handlers import handle_analysis_completed
from tests.test_onboarding import _body, live_publisher  # noqa: F401  (fixture)
from tests.test_team_routes import DONO_SUB, _invite, _token, company  # noqa: F401  (fixture)

TOKEN = "eyJhbGciOiJSUzI1NiJ9.token-secreto-do-usuario.assinatura"
HEADER_TOKEN = "Bearer header-secreto-123"
CNPJ = "11222333000181"


def _as(subject):
    app.dependency_overrides[require_auth] = lambda: Principal(
        token=TOKEN, subject=subject, permissions=frozenset({"read:self", "write:self"})
    )


def _all_logs(caplog) -> str:
    """Mensagem + campos extras de cada linha, como o JsonFormatter grava em produção.

    Ignora o httpx, que aqui é o cliente do TestClient (fora da API). Em produção o uvicorn roda com
    `--no-access-log`: a única linha de acesso é a do RequestIDMiddleware.
    """
    formatter = JsonFormatter()
    return "\n".join(formatter.format(r) for r in caplog.records if not r.name.startswith(("httpx", "httpcore")))


def _assert_clean(text, *secrets):
    for secret in (TOKEN, HEADER_TOKEN, "header-secreto-123", *secrets):
        assert secret not in text


def test_submit_onboarding_logs_no_token_cnpj_or_payload(client, live_publisher, caplog):
    caplog.set_level(logging.DEBUG)
    _as("auth0|novo")
    response = client.put("/me/onboarding", json=_body(enviar=True), headers={"Authorization": HEADER_TOKEN})
    assert response.status_code == 200
    live_publisher.exchange.publish.assert_awaited()  # o evento com o CNPJ foi publicado, não logado
    text = _all_logs(caplog)
    assert '"path": "/me/onboarding"' in text  # a linha de acesso existe
    _assert_clean(text, CNPJ, "11.222.333/0001-81", "contato@padaria.com", "Padaria de bairro",
                  "faturamento_mensal")


def test_duplicate_cnpj_message_is_masked(client, company):
    _as("auth0|outro")
    response = client.put("/me/onboarding", json=_body())
    assert response.status_code == 409
    assert CNPJ not in response.text and "0181" in response.json()["detail"]


def test_duplicate_cpf_message_is_masked(client, sample_customer_payload):
    client.post("/customers", json=sample_customer_payload)
    response = client.post("/customers", json=sample_customer_payload)
    assert response.status_code == 409
    assert sample_customer_payload["cpf"] not in response.text and "8900" in response.text


def test_invite_and_accept_never_log_the_invite_token(client, company, caplog):
    caplog.set_level(logging.DEBUG)
    _as(DONO_SUB)
    response = _invite(client, email="segredo@empresa.com")
    invite_token = _token(response)
    _as("auth0|convidado")
    assert client.post(f"/me/team/invites/{invite_token}/accept").status_code == 200
    text = _all_logs(caplog)
    assert "/me/team/invites/***/accept" in text
    _assert_clean(text, invite_token, "segredo@empresa.com")


def test_access_log_has_no_headers_query_or_body(client, caplog):
    caplog.set_level(logging.DEBUG)
    client.post("/customers?cpf=12345678900", json={"cpf": "98765432100"},
                headers={"Authorization": HEADER_TOKEN, "Cookie": "sessao=abc"})
    access = [r for r in caplog.records if r.name == "app.access"][-1]
    extras = {k for k in vars(access) if k not in vars(logging.makeLogRecord({}))}
    assert extras <= {"method", "path", "status", "duration_ms", "message", "asctime"}
    _assert_clean(_all_logs(caplog), "12345678900", "98765432100", "sessao=abc")


@pytest.mark.parametrize("path, expected", [
    ("/me/team/invites/abc_DEF-123/accept", "/me/team/invites/***/accept"),
    ("/onboarding/me/team/invites/x/accept", "/onboarding/me/team/invites/***/accept"),
    ("/me/team/invites", "/me/team/invites"),
    ("/me", "/me"),
    (None, None),
])
def test_safe_path(path, expected):
    assert safe_path(path) == expected


def test_invalid_event_log_has_no_input_values(db_session, caplog):
    caplog.set_level(logging.WARNING)
    payload = {"event_id": "e1", "customer_id": "nao-e-numero", "cnpj": CNPJ, "observacoes": "dado sensível"}
    assert handle_analysis_completed(db_session, payload) == "invalid"
    text = _all_logs(caplog)
    assert "inválido" in text
    _assert_clean(text, CNPJ, "nao-e-numero", "dado sensível")


def test_nan_body_is_422_not_500(client, company):
    _as(DONO_SUB)
    response = client.post(
        "/me/team/invites", headers={"Content-Type": "application/json"},
        content='{"email": "z@x.com", "nome": "Z", "papel": "LEITURA", "limite_pagamento": NaN}',
    )
    assert response.status_code == 422
    assert response.json()["detail"][0]["input"] == "nan"
