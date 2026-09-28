from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import AnamnesisIn, AnamnesisOut, CustomerCreate, CustomerOut
from app.services import (
    CustomerAlreadyExistsError,
    CustomerNotFoundError,
    CustomerService,
)

router = APIRouter(prefix="/customers", tags=["customers"])


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)):
    service = CustomerService(db)
    try:
        customer = service.create(payload)
    except CustomerAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return customer


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    service = CustomerService(db)
    try:
        return service.get(customer_id)
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.put("/{customer_id}/anamnesis", response_model=AnamnesisOut)
def upsert_anamnesis(customer_id: int, payload: AnamnesisIn, db: Session = Depends(get_db)):
    service = CustomerService(db)
    try:
        return service.upsert_anamnesis(customer_id, payload)
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
