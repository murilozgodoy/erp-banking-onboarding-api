from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Customer


class CustomerRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, customer_id: int) -> Customer | None:
        return self.db.get(Customer, customer_id)

    def get_by_cpf(self, cpf: str) -> Customer | None:
        stmt = select(Customer).where(Customer.cpf == cpf)
        return self.db.execute(stmt).scalar_one_or_none()

    def add(self, customer: Customer) -> Customer:
        self.db.add(customer)
        self.db.commit()
        self.db.refresh(customer)
        return customer

    def update(self, customer: Customer) -> Customer:
        self.db.add(customer)
        self.db.commit()
        self.db.refresh(customer)
        return customer

    def list_all(self, limit: int = 100) -> list[Customer]:
        stmt = select(Customer).limit(limit)
        return list(self.db.execute(stmt).scalars().all())
