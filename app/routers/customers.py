from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.core.security import require_permission
from app.schemas import AnamnesisIn, AnamnesisOut, CustomerCreate, CustomerOut
from app.services import (
    CustomerAlreadyExistsError,
    CustomerNotFoundError,
    CustomerService,
)

router = APIRouter(prefix="/customers", tags=["customers"])


@router.post(
    "",
    response_model=CustomerOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("write:customers"))],
)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db)):
    service = CustomerService(db)
    try:
        customer = service.create(payload)
    except CustomerAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return customer


@router.get(
    "/{customer_id}",
    response_model=CustomerOut,
    dependencies=[Depends(require_permission("read:customers"))],
)
def get_customer(customer_id: int, db: Session = Depends(get_db)):
    service = CustomerService(db)
    try:
        return service.get(customer_id)
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.put(
    "/{customer_id}/anamnesis",
    response_model=AnamnesisOut,
    dependencies=[Depends(require_permission("write:customers"))],
)
def upsert_anamnesis(customer_id: int, payload: AnamnesisIn, db: Session = Depends(get_db)):
    service = CustomerService(db)
    try:
        return service.upsert_anamnesis(customer_id, payload)
    except CustomerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
