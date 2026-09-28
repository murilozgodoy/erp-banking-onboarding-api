from sqlalchemy.orm import Session

from app.models import Address, Anamnesis, Customer, FinancialProfile
from app.repositories import AnamnesisRepository, CustomerRepository
from app.schemas import AnamnesisIn, CustomerCreate


class CustomerAlreadyExistsError(Exception):
    pass


class CustomerNotFoundError(Exception):
    pass


class CustomerService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = CustomerRepository(db)
        self.anamnesis_repo = AnamnesisRepository(db)

    def create(self, data: CustomerCreate) -> Customer:
        if self.repo.get_by_cpf(data.cpf):
            raise CustomerAlreadyExistsError(f"CPF {data.cpf} já cadastrado")

        customer = Customer(
            nome=data.nome,
            cpf=data.cpf,
            email=data.email,
            telefone=data.telefone,
        )
        if data.address:
            customer.address = Address(**data.address.model_dump())
        if data.financial_profile:
            customer.financial_profile = FinancialProfile(**data.financial_profile.model_dump())
        return self.repo.add(customer)

    def get(self, customer_id: int) -> Customer:
        customer = self.repo.get(customer_id)
        if customer is None:
            raise CustomerNotFoundError(f"Cliente {customer_id} não encontrado")
        return customer

    def upsert_anamnesis(self, customer_id: int, data: AnamnesisIn) -> Anamnesis:
        self.get(customer_id)
        return self.anamnesis_repo.upsert(
            customer_id=customer_id,
            dividas=data.dividas_ativas,
            comp_renda=data.comprometimento_renda,
        )
