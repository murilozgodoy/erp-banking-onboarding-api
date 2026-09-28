import pytest

from app.schemas import AnamnesisIn, CustomerCreate
from app.services import (
    CustomerAlreadyExistsError,
    CustomerNotFoundError,
    CustomerService,
)


def _payload():
    return CustomerCreate(
        nome="Maria",
        cpf="98765432100",
        email="maria@example.com",
        telefone="11988887777",
    )


def test_create_customer_persists(db_session):
    service = CustomerService(db_session)
    customer = service.create(_payload())
    assert customer.id is not None
    assert customer.cpf == "98765432100"


def test_create_customer_duplicate_cpf_raises(db_session):
    service = CustomerService(db_session)
    service.create(_payload())
    with pytest.raises(CustomerAlreadyExistsError):
        service.create(_payload())


def test_get_customer_not_found_raises(db_session):
    service = CustomerService(db_session)
    with pytest.raises(CustomerNotFoundError):
        service.get(999)


def test_upsert_anamnesis_creates_and_updates(db_session):
    service = CustomerService(db_session)
    customer = service.create(_payload())

    first = service.upsert_anamnesis(
        customer.id, AnamnesisIn(dividas_ativas=1500.0, comprometimento_renda=25.0)
    )
    assert first.dividas_ativas == 1500.0

    second = service.upsert_anamnesis(
        customer.id, AnamnesisIn(dividas_ativas=2000.0, comprometimento_renda=30.0)
    )
    assert second.id == first.id
    assert second.dividas_ativas == 2000.0
    assert second.comprometimento_renda == 30.0


def test_upsert_anamnesis_customer_not_found(db_session):
    service = CustomerService(db_session)
    with pytest.raises(CustomerNotFoundError):
        service.upsert_anamnesis(
            42, AnamnesisIn(dividas_ativas=0.0, comprometimento_renda=0.0)
        )


def test_create_customer_with_full_payload(db_session):
    service = CustomerService(db_session)
    payload = CustomerCreate(
        nome="Ana",
        cpf="11122233344",
        email="ana@example.com",
        telefone="11966665555",
        address={
            "rua": "Av Paulista",
            "numero": "1000",
            "cidade": "São Paulo",
            "estado": "SP",
            "cep": "01310000",
        },
        financial_profile={
            "renda_mensal": 12000.0,
            "patrimonio": 200000.0,
            "ocupacao": "PJ",
        },
    )
    customer = service.create(payload)
    assert customer.address is not None
    assert customer.address.cidade == "São Paulo"
    assert customer.financial_profile.renda_mensal == 12000.0


def test_repository_list_all(db_session):
    service = CustomerService(db_session)
    service.create(_payload())
    result = service.repo.list_all()
    assert len(result) == 1
