"""Transfers (specs/api.md §16)."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.clock import today
from app.db.session import get_db
from app.models import Transfer
from app.schemas.common import Items
from app.schemas.transfers import TransferCreate, TransferOut
from app.services import transfers as svc
from app.services.auth import CurrentUser
from app.services.reference import get_owned

router = APIRouter(prefix="/transfers", tags=["transfers"])


@router.get("", response_model=Items[TransferOut])
def list_transfers(
    start: date | None = Query(None, alias="from"),
    to: date | None = None,
    account_id: uuid.UUID | None = None,
    investment_id: uuid.UUID | None = None,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = svc.list_transfers(
        db, current.household.id, start, to, account_id, investment_id
    )
    return Items(items=[svc.transfer_out(t) for t in rows])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TransferOut)
def create_transfer(
    body: TransferCreate,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    transfer = svc.create_transfer(db, current.household, current.user, body, today())
    db.commit()
    db.refresh(transfer)
    return svc.transfer_out(transfer)


@router.delete("/{transfer_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transfer(
    transfer_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    svc.delete_transfer(db, get_owned(db, Transfer, current.household.id, transfer_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
