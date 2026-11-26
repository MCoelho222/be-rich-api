"""Investments (specs/api.md §15)."""

import uuid

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.clock import today
from app.db.session import get_db
from app.models import Investment
from app.schemas.common import Items
from app.schemas.investments import InvestmentCreate, InvestmentOut, InvestmentPatch
from app.services import investments as svc
from app.services.auth import CurrentUser
from app.services.reference import get_owned

router = APIRouter(prefix="/investments", tags=["investments"])


@router.get("", response_model=Items[InvestmentOut])
def list_investments(current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return Items(items=svc.list_investments(db, current.household.id))


@router.post("", status_code=status.HTTP_201_CREATED, response_model=InvestmentOut)
def create_investment(
    body: InvestmentCreate, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
):
    investment = svc.create_investment(db, current.household, body, today())
    db.commit()
    return investment


@router.patch("/{investment_id}", response_model=InvestmentOut)
def update_investment(
    investment_id: uuid.UUID,
    body: InvestmentPatch,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    investment = get_owned(db, Investment, current.household.id, investment_id)
    svc.update_investment(db, investment, body)
    db.commit()
    db.refresh(investment)
    return investment


@router.delete("/{investment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_investment(
    investment_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> Response:
    db.delete(get_owned(db, Investment, current.household.id, investment_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
