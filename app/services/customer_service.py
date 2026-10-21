from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import Address, Anamnesis, Customer, FinancialProfile
from app.schemas import AnamnesisIn, CustomerCreate


class CustomerAlreadyExistsError(Exception):
    pass


class CustomerNotFoundError(Exception):
    pass


class CustomerService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, data: CustomerCreate) -> Customer:
        if self.db.scalar(select(Customer).where(Customer.cpf == data.cpf)):
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
        self.db.add(customer)
        self.db.commit()
        self.db.refresh(customer)
        return customer

    def search(self, q: str | None = None, limit: int = 50, offset: int = 0) -> list[Customer]:
        """Lista clientes (mais recentes primeiro), filtrando por nome ou dígitos do CPF."""
        stmt = (
            select(Customer)
            .options(
                selectinload(Customer.address),
                selectinload(Customer.financial_profile),
                selectinload(Customer.anamnesis),
            )
            .order_by(Customer.id.desc())
            .limit(limit)
            .offset(offset)
        )
        term = (q or "").strip()
        if term:
            conditions = [Customer.nome.ilike(f"%{term}%")]
            digits = "".join(ch for ch in term if ch.isdigit())
            if digits:
                conditions.append(Customer.cpf.contains(digits))
            stmt = stmt.where(or_(*conditions))
        return list(self.db.scalars(stmt))

    def get(self, customer_id: int) -> Customer:
        customer = self.db.get(Customer, customer_id)
        if customer is None:
            raise CustomerNotFoundError(f"Cliente {customer_id} não encontrado")
        return customer

    def upsert_anamnesis(self, customer_id: int, data: AnamnesisIn) -> Anamnesis:
        customer = self.get(customer_id)
        anamnesis = customer.anamnesis or Anamnesis(customer_id=customer_id)
        anamnesis.dividas_ativas = data.dividas_ativas
        anamnesis.comprometimento_renda = data.comprometimento_renda
        self.db.add(anamnesis)
        self.db.commit()
        self.db.refresh(anamnesis)
        return anamnesis
