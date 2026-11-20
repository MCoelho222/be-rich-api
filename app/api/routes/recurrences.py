"""Recurrences, occurrences and the overdue list (specs/api.md §12)."""

import uuid
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.clock import today
from app.db.session import get_db
from app.domain.dates import add_months
from app.domain.enums import EntryType
from app.models import Recurrence
from app.schemas.common import Items
from app.schemas.entries import ExpenseOut, IncomeOut
from app.schemas.recurrences import (
    AmountChanged,
    ChangeAmountIn,
    EndIn,
    NextOccurrence,
    OccurrenceOut,
    OverdueOut,
    RecurrenceCreate,
    RecurrenceCreated,
    RecurrenceOut,
    RecurrencePatch,
    RegisterIn,
)
from app.services import recurrences as svc
from app.services.auth import CurrentUser

router = APIRouter(tags=["recurrences"])


def to_out(db: Session, rec: Recurrence, now: date) -> RecurrenceOut:
    nxt = svc.next_occurrence(db, rec, now)
    out = RecurrenceOut.model_validate(
        {
            **{c.key: getattr(rec, c.key) for c in Recurrence.__mapper__.column_attrs},
            "status": svc.status_of(rec, now),
            "next_occurrence": NextOccurrence(occurrence_date=nxt.occurrence_date, payment_date=nxt.payment_date,
                                              status=nxt.status) if nxt else None,  # fmt: skip
        }
    )
    return out


def row_out(rec: Recurrence, row) -> ExpenseOut | IncomeOut:
    model = ExpenseOut if rec.type is EntryType.EXPENSE else IncomeOut
    return model.model_validate(row)


def occurrence_out(o: svc.Occurrence) -> OccurrenceOut:
    return OccurrenceOut(
        occurrence_date=o.occurrence_date, payment_date=o.payment_date, expected_amount=o.expected_amount,
        currency=o.currency, status=o.status, row_id=o.row_id,
    )  # fmt: skip


@router.get("/recurrences", response_model=Items[RecurrenceOut])
def list_recurrences(
    type: EntryType | None = None,  # noqa: A002 - API parameter name
    status_: Literal["active", "paused", "ended", "all"] = Query("active", alias="status"),
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = today()
    stmt = select(Recurrence).where(Recurrence.household_id == current.household.id)
    if type is not None:
        stmt = stmt.where(Recurrence.type == type)
    recs = db.scalars(stmt.order_by(Recurrence.type, Recurrence.day_of_month, Recurrence.created_at)).all()
    wanted = None if status_ == "all" else status_.upper()
    return Items(items=[to_out(db, r, now) for r in recs if wanted is None or svc.status_of(r, now) == wanted])


@router.get("/recurrences/{recurrence_id}", response_model=RecurrenceOut)
def get_recurrence(recurrence_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return to_out(db, svc.get(db, current.household.id, recurrence_id), today())


@router.post("/recurrences", status_code=status.HTTP_201_CREATED, response_model=RecurrenceCreated)
def create_recurrence(body: RecurrenceCreate, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Create the template and, optionally, register its first occurrence in the same
    transaction (the "Repeats" toggle in the entry forms, ui-behavior §6.4)."""
    now = today()
    rec = svc.create(db, current.household, current.user, body, now)
    registered = None
    if body.register_first is not None:
        first = body.register_first
        overrides = {"amount": first.amount}
        if "description" in first.model_fields_set:
            overrides["description"] = first.description
        registered = svc.register(db, current.household, current.user, rec, first.occurrence_date, overrides)
    db.commit()
    return RecurrenceCreated(recurrence=to_out(db, rec, now), registered=row_out(rec, registered) if registered else None)


@router.patch("/recurrences/{recurrence_id}", response_model=RecurrenceOut)
def update_recurrence(
    recurrence_id: uuid.UUID,
    body: RecurrencePatch,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rec = svc.get(db, current.household.id, recurrence_id)
    svc.update_recurrence(db, rec, {f: getattr(body, f) for f in body.model_fields_set})
    db.commit()
    return to_out(db, rec, today())


def _set_active(recurrence_id, active: bool, current: CurrentUser, db: Session) -> RecurrenceOut:
    rec = svc.get(db, current.household.id, recurrence_id)
    rec.is_active = active
    db.commit()
    return to_out(db, rec, today())


@router.post("/recurrences/{recurrence_id}/pause", response_model=RecurrenceOut)
def pause(recurrence_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return _set_active(recurrence_id, False, current, db)


@router.post("/recurrences/{recurrence_id}/resume", response_model=RecurrenceOut)
def resume(recurrence_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return _set_active(recurrence_id, True, current, db)


@router.post("/recurrences/{recurrence_id}/end", response_model=RecurrenceOut)
def end_recurrence(
    recurrence_id: uuid.UUID,
    body: EndIn | None = None,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rec = svc.get(db, current.household.id, recurrence_id)
    svc.end(db, rec, (body.end_date if body else None) or today())
    db.commit()
    return to_out(db, rec, today())


@router.post("/recurrences/{recurrence_id}/change-amount", response_model=AmountChanged)
def change_amount(
    recurrence_id: uuid.UUID,
    body: ChangeAmountIn,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rec = svc.get(db, current.household.id, recurrence_id)
    new = svc.change_amount(db, rec, body.effective_date, body.amount, current.user)
    db.commit()
    now = today()
    return AmountChanged(ended=to_out(db, rec, now), created=to_out(db, new, now))


@router.delete("/recurrences/{recurrence_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_recurrence(recurrence_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    svc.delete(db, svc.get(db, current.household.id, recurrence_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Occurrences -------------------------------------------------------------------


@router.get("/recurrences/{recurrence_id}/occurrences", response_model=Items[OccurrenceOut])
def list_occurrences(
    recurrence_id: uuid.UUID,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Defaults to the current month and the next 11."""
    now = today()
    start = from_ or now.replace(day=1)
    end = to or add_months(start.replace(day=1), 12) - timedelta(days=1)
    rec = svc.get(db, current.household.id, recurrence_id)
    return Items(items=[occurrence_out(o) for o in svc.occurrences(db, rec, start, end, now)])


@router.post(
    "/recurrences/{recurrence_id}/occurrences/{occurrence_date}/register",
    status_code=status.HTTP_201_CREATED,
    response_model=ExpenseOut | IncomeOut,
)
def register_occurrence(
    recurrence_id: uuid.UUID,
    occurrence_date: date,
    body: RegisterIn | None = None,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rec = svc.get(db, current.household.id, recurrence_id)
    overrides = {f: getattr(body, f) for f in body.model_fields_set} if body else {}
    row = svc.register(db, current.household, current.user, rec, occurrence_date, overrides)
    db.commit()
    return row_out(rec, row)


@router.post("/recurrences/{recurrence_id}/occurrences/{occurrence_date}/skip", status_code=status.HTTP_204_NO_CONTENT)
def skip_occurrence(
    recurrence_id: uuid.UUID, occurrence_date: date,
    current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db),
):  # fmt: skip
    svc.skip(db, svc.get(db, current.household.id, recurrence_id), occurrence_date)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/recurrences/{recurrence_id}/occurrences/{occurrence_date}/skip", status_code=status.HTTP_204_NO_CONTENT)
def unskip_occurrence(
    recurrence_id: uuid.UUID, occurrence_date: date,
    current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db),
):  # fmt: skip
    svc.unskip(db, svc.get(db, current.household.id, recurrence_id), occurrence_date)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/occurrences/overdue", response_model=Items[OverdueOut])
def list_overdue(current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return Items(
        items=[
            OverdueOut(**occurrence_out(o).model_dump(), recurrence_id=o.recurrence_id)
            for o in svc.overdue(db, current.household.id, today())
        ]
    )
