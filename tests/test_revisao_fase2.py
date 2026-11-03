"""Regressões da revisão da Fase 2 (concorrência, limites do PostgreSQL e entradas inválidas)."""
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.main import app
from app.models import Customer
from app.schemas.onboarding import OnboardingIn
from app.services import onboarding_service
from app.services.onboarding_service import OnboardingConflictError, OnboardingService
from app.templates import validate_respostas
from tests.factories import make_pj
from tests.test_onboarding import EMPRESA, _body
from tests.test_templates import respostas_validas


def _status_changes_after_read(db, customer_id, status):
    """Simula outra transação que já mudou o status depois da nossa leitura (identity map velho)."""
    db.execute(text("UPDATE customers SET onboarding_status = :s WHERE id = :id"),
               {"s": status, "id": customer_id})


def test_autosave_does_not_revert_concurrent_submit(db_session, monkeypatch):
    """Autosave (rascunho) que leu RASCUNHO não pode sobrescrever o envio concorrente (EM_ANALISE)."""
    customer = make_pj(db_session, sub="auth0|race", status="RASCUNHO")
    real_find = onboarding_service.find_by_sub

    def find_then_race(db, sub):
        found = real_find(db, sub)
        _status_changes_after_read(db, found.id, "EM_ANALISE")
        return found

    monkeypatch.setattr(onboarding_service, "find_by_sub", find_then_race)
    with pytest.raises(OnboardingConflictError):
        OnboardingService(db_session).save("auth0|race", OnboardingIn(empresa=EMPRESA))
    db_session.expire_all()
    assert db_session.get(Customer, customer.id).onboarding_status == "EM_ANALISE"


def test_two_analysts_deciding_at_once(client, engine, db_session):
    """A segunda decisão (que leu ANALISE_MANUAL antes da primeira commitar) deve dar 409."""
    customer = make_pj(db_session, status="ANALISE_MANUAL")

    class RacingSession(Session):
        def get(self, *args, **kwargs):
            found = super().get(*args, **kwargs)
            _status_changes_after_read(self, found.id, "APROVADO")
            return found

    def override():
        session = RacingSession(bind=engine, autoflush=False)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override
    response = client.post(f"/onboarding/reviews/{customer.id}/decision", json={"decisao": "REPROVADO"})
    assert response.status_code == 409
    db_session.expire_all()
    assert db_session.get(Customer, customer.id).onboarding_status != "REPROVADO"
    assert customer.business_profile.reviewed_by is None


def test_long_razao_social_fits_nome_column(client, db_session):
    """razao_social aceita 160 caracteres, mas customers.nome é VARCHAR(120) (DataError no PostgreSQL)."""
    razao = "A" * 160
    response = client.put("/me/onboarding", json={"empresa": {"razao_social": razao}})
    assert response.status_code == 200
    customer = db_session.get(Customer, client.get("/me").json()["customer_id"])
    assert customer.razao_social == razao
    assert len(customer.nome) <= Customer.__table__.c.nome.type.length


def test_funcionarios_out_of_int4_range_is_422(client):
    """business_profiles.funcionarios é INTEGER: valor acima de 2^31-1 estoura no PostgreSQL (500)."""
    response = client.put("/me/onboarding", json={"empresa": {"funcionarios": 2**31}})
    assert response.status_code == 422


@pytest.mark.parametrize("cnpj", [
    "１１２２２３３３０００１８１",  # dígitos full-width
    "11222333000181abc",            # letras descartadas em silêncio
])
def test_cnpj_rejects_non_ascii_digits_and_garbage(client, cnpj):
    response = client.put("/me/onboarding", json={"empresa": {"cnpj": cnpj}})
    assert response.status_code == 422


def test_huge_integer_answer_is_validation_error_not_500():
    respostas = respostas_validas("alimentacao") | {"faturamento_mensal": 10**400}
    erros = validate_respostas("alimentacao", respostas)
    assert {"campo": "faturamento_mensal", "erro": "Informe um número."} in erros


def test_huge_integer_answer_on_submit_returns_422(client):
    body = _body(enviar=True)
    body["respostas"]["faturamento_mensal"] = 10**400
    response = client.put("/me/onboarding", json=body)
    assert response.status_code == 422


def test_gauge_failure_after_commit_does_not_lose_submitted_event(client, live_publisher, monkeypatch):
    """Commit feito: falha ao atualizar o gauge não pode virar 500 sem publicar o evento."""

    class BrokenGauge:
        def set(self, value):
            raise RuntimeError("falha no gauge")

    monkeypatch.setattr(onboarding_service, "ONBOARDING_MANUAL_QUEUE", BrokenGauge())
    response = client.put("/me/onboarding", json=_body(enviar=True))
    assert response.status_code == 200
    assert live_publisher.exchange.publish.await_args.kwargs["routing_key"] == "customer.onboarding_submitted"


@pytest.fixture()
def live_publisher(client, broker):
    from app.events import EventPublisher

    original = client.app.state.publisher
    client.app.state.publisher = EventPublisher("amqp://localhost/")
    yield broker
    client.app.state.publisher = original
