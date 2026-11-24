"""Recurrences: fixed expenses and incomes (specs/schemas.md §12).

A Recurrence is a template. Rows are only created when an occurrence is
registered. Services flush but never commit; routes own the transaction.
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.errors import ApiError, validation_error
from app.domain.business_days import next_business_day
from app.domain.credit import CardCycle, purchase_window, statement_due_in
from app.domain.dates import add_months, clamp_date
from app.domain.enums import CARD_METHODS, EntryType, OccurrenceStatus, PaymentMethod
from app.domain.payments import payment_dates
from app.domain.recurrence import RecurrenceRule, occurrence_dates, occurrence_status
from app.models import Card, Household, Recurrence, User
from app.schemas.common import blank_to_none
from app.services import entries
from app.services.calendar import load_holidays
from app.services.entries import EXPENSE, INCOME, Errors, Kind, _err

FAR_PAST = date(1900, 1, 1)


def kind_of(entry_type: EntryType) -> Kind:
    return EXPENSE if entry_type is EntryType.EXPENSE else INCOME


def status_of(rec: Recurrence, today: date) -> str:
    if rec.end_date is not None and rec.end_date < today:
        return "ENDED"
    return "ACTIVE" if rec.is_active else "PAUSED"


def is_card_bill(rec: Recurrence) -> bool:
    """A credit card fixed expense: its occurrences are the card's due dates (§12.1)."""
    return rec.type is EntryType.EXPENSE and rec.payment_method is PaymentMethod.CREDIT and rec.card_id is not None


def rule_of(rec: Recurrence) -> RecurrenceRule:
    return RecurrenceRule(
        start_date=rec.start_date,
        day_of_month=rec.day_of_month,
        interval_months=rec.interval_months,
        end_date=rec.end_date,
        is_active=rec.is_active,
        skipped_dates=frozenset(rec.skipped_dates or ()),
    )


def get(db: Session, household_id: uuid.UUID, recurrence_id: uuid.UUID) -> Recurrence:
    rec = db.get(Recurrence, recurrence_id)
    if rec is None or rec.household_id != household_id:
        raise ApiError(404, "NOT_FOUND", "Recurrence not found.")
    return rec


# --- Occurrences -------------------------------------------------------------------


class OccurrenceCalculator:
    """Payment dates for a recurrence's occurrences, sharing one holiday lookup."""

    def __init__(self, db: Session, rec: Recurrence, first_year: int, last_year: int) -> None:
        self.rec = rec
        self.kind = kind_of(rec.type)
        card = db.get(Card, rec.card_id) if rec.card_id else None
        self.cycle = CardCycle(card.best_buy_day, card.due_day) if card and rec.payment_method is PaymentMethod.CREDIT else None
        self.holidays = load_holidays(db, first_year, last_year + 1)

    def payment_date(self, occurrence: date) -> date:
        if self.cycle is not None and self.kind.has_card:
            # A credit card fixed expense occurs on the card's due dates (§12.1): it is paid
            # with the statement due that day, moved to the next business day.
            return next_business_day(occurrence, self.holidays)
        return payment_dates(
            self.kind.entry_type, self.rec.payment_method, occurrence, 1, self.holidays, self.cycle
        )[0]


def registered_rows(db: Session, rec: Recurrence) -> dict[date, uuid.UUID]:
    model = kind_of(rec.type).model
    rows = db.execute(select(model.occurrence_date, model.id).where(model.recurrence_id == rec.id)).all()
    return {occ: row_id for occ, row_id in rows}


@dataclass(frozen=True)
class Occurrence:
    recurrence_id: uuid.UUID
    occurrence_date: date
    payment_date: date
    expected_amount: Decimal
    currency: Any
    status: OccurrenceStatus
    row_id: uuid.UUID | None


def occurrences(db: Session, rec: Recurrence, start: date, end: date, today: date) -> list[Occurrence]:
    registered = registered_rows(db, rec)
    calc = OccurrenceCalculator(db, rec, max(start, rec.start_date).year, max(start, end).year)
    skipped = set(rec.skipped_dates or ())
    return [
        Occurrence(
            rec.id, occ, calc.payment_date(occ), rec.amount, rec.currency,
            occurrence_status(occ, today, registered=occ in registered, skipped=occ in skipped),
            registered.get(occ),
        )  # fmt: skip
        for occ in occurrence_dates(rule_of(rec), start, end)
    ]


def next_occurrence(db: Session, rec: Recurrence, today: date) -> Occurrence | None:
    """First unregistered, non-skipped occurrence from the current month on (active only)."""
    if status_of(rec, today) != "ACTIVE":
        return None
    start = today.replace(day=1)
    for horizon in (13, 37):  # months; yearly recurrences may need the longer window
        for occ in occurrences(db, rec, start, add_months(start, horizon), today):
            if occ.status in (OccurrenceStatus.PENDING, OccurrenceStatus.FUTURE):
                return occ
    return None


def overdue(db: Session, household_id: uuid.UUID, today: date) -> list[Occurrence]:
    """Valid, unregistered occurrences from earlier months, oldest first (§12.1)."""
    last_month_end = today.replace(day=1) - timedelta(days=1)
    result: list[Occurrence] = []
    recs = db.scalars(
        select(Recurrence).where(
            Recurrence.household_id == household_id,
            Recurrence.is_active.is_(True),
            Recurrence.start_date <= last_month_end,
        )
    )
    for rec in recs:
        result += [o for o in occurrences(db, rec, FAR_PAST, last_month_end, today) if o.status is OccurrenceStatus.OVERDUE]
    return sorted(result, key=lambda o: (o.occurrence_date, str(o.recurrence_id)))


def _require_occurrence(rec: Recurrence, occurrence: date) -> None:
    if occurrence not in occurrence_dates(rule_of(rec), occurrence, occurrence):
        raise ApiError(404, "NOT_FOUND", "This date is not an occurrence of the recurrence.")


# --- Create / update ---------------------------------------------------------------


def _validate(
    db: Session, household_id: uuid.UUID, kind: Kind, values: dict[str, Any], changed: set[str], errors: Errors
) -> entries.Payment | None:
    """Validate the final state of a recurrence; only re-check references in `changed`."""
    if values["amount"] is None or values["amount"] <= 0:
        _err(errors, "amount", "Must be greater than zero")
    if values["end_date"] is not None and values["end_date"] < values["start_date"]:
        _err(errors, "end_date", "Must be on or after start_date")
    if "person_id" in changed:
        entries._check_member(db, household_id, values["person_id"], "person_id", errors)
    if "category_id" in changed:
        entries._check_category(db, kind, household_id, values["category_id"], errors)
    if not kind.has_card and values.get("card_id") is not None:
        _err(errors, "card_id", "Only for expenses")
    if changed & {"payment_method", "card_id", "account_id"}:
        return entries._resolve_payment(
            db, kind, household_id, method=values["payment_method"], card_id=values.get("card_id"),
            account_id=values.get("account_id"), installments=1, prefix="", errors=errors,
        )  # fmt: skip
    return None


def create(db: Session, household: Household, caller: User, body: Any, today: date) -> Recurrence:
    kind = kind_of(body.type)
    start = body.start_date or today
    values = {
        "person_id": body.person_id or caller.id,
        "amount": body.amount,
        "payment_method": body.payment_method,
        "card_id": body.card_id,
        "account_id": body.account_id,
        "category_id": body.category_id,
        "start_date": start,
        "end_date": body.end_date,
    }
    errors: Errors = {}
    payment = _validate(db, household.id, kind, values, set(values), errors)
    if errors:
        raise validation_error(errors)
    assert payment is not None and payment.account is not None
    rec = Recurrence(
        household_id=household.id, type=body.type, person_id=values["person_id"], amount=body.amount,
        currency=body.currency or household.default_currency, payment_method=body.payment_method,
        card_id=payment.card.id if payment.card else None, account_id=payment.account.id,
        category_id=body.category_id, description=blank_to_none(body.description),
        interval_months=body.interval_months,
        day_of_month=(
            payment.card.due_day if payment.card and body.payment_method is PaymentMethod.CREDIT and kind.has_card
            else body.day_of_month or start.day
        ),
        start_date=start, end_date=body.end_date, skipped_dates=[], is_active=True, created_by_id=caller.id,
    )  # fmt: skip
    db.add(rec)
    db.flush()
    return rec


EDITABLE = (
    "person_id", "amount", "currency", "payment_method", "card_id", "account_id", "category_id",
    "description", "interval_months", "day_of_month", "start_date", "end_date",
)  # fmt: skip
NOT_NULL = ("person_id", "amount", "currency", "payment_method", "category_id", "interval_months", "day_of_month", "start_date")


def update_recurrence(db: Session, rec: Recurrence, changes: dict[str, Any]) -> None:
    """Edit the template. Registered rows are never modified (§12.3)."""
    errors: Errors = {}
    for field in NOT_NULL:
        if field in changes and changes[field] is None:
            _err(errors, field, "Can't be empty")
    if errors:
        raise validation_error(errors)
    kind = kind_of(rec.type)
    values = {f: changes.get(f, getattr(rec, f)) for f in EDITABLE}
    # A new method may need a different card/account: don't carry stale ones over.
    if "payment_method" in changes:
        if "card_id" not in changes and values["payment_method"] not in CARD_METHODS:
            values["card_id"] = None
        if "account_id" not in changes and (kind.has_card and values["payment_method"] in CARD_METHODS):
            values["account_id"] = None
        if "account_id" not in changes and (values["payment_method"] is PaymentMethod.CASH) != (rec.payment_method is PaymentMethod.CASH):
            values["account_id"] = None
    payment = _validate(db, rec.household_id, kind, values, set(changes), errors)
    if errors:
        raise validation_error(errors)
    for field in EDITABLE:
        if field in ("card_id", "account_id"):
            continue
        if field in changes:
            setattr(rec, field, blank_to_none(changes[field]) if field == "description" else changes[field])
    if payment is not None:
        rec.card_id = payment.card.id if payment.card else None
        rec.account_id = payment.account.id
    if is_card_bill(rec):
        card = db.get(Card, rec.card_id)
        assert card is not None
        rec.day_of_month = card.due_day  # credit card fixed expenses follow the card's due day
    db.flush()


def follow_card_due_day(db: Session, card: Card, old_due_day: int) -> None:
    """After a card's due_day changes, its credit fixed expenses move to the new day. Registered
    payments and skips keep pointing at the same month's occurrence (schemas §10.4, §12.1)."""
    if card.due_day == old_due_day:
        return
    recs = db.scalars(
        select(Recurrence).where(
            Recurrence.card_id == card.id,
            Recurrence.type == EntryType.EXPENSE,
            Recurrence.payment_method == PaymentMethod.CREDIT,
        )
    ).all()
    def move(d: date) -> date:
        return clamp_date(d.year, d.month, card.due_day)

    for rec in recs:
        rec.day_of_month = card.due_day
        rec.start_date = rec.start_date.replace(day=1)
        rec.skipped_dates = sorted({move(d) for d in rec.skipped_dates or ()})
        model = kind_of(rec.type).model
        for row in db.scalars(select(model).where(model.recurrence_id == rec.id)):
            row.occurrence_date = move(row.occurrence_date)
    db.flush()


def end(db: Session, rec: Recurrence, end_date: date) -> None:
    if end_date < rec.start_date:
        raise validation_error({"end_date": ["Must be on or after start_date"]})
    rec.end_date = end_date
    db.flush()


def change_amount(db: Session, rec: Recurrence, effective: date, amount: Decimal, caller: User) -> Recurrence:
    """End the recurrence the day before `effective` and continue with a copy at the
    new amount (§12.3). Payments already registered for occurrences on or after
    `effective` move to the copy, so they aren't shown as unpaid again."""
    errors: Errors = {}
    if amount <= 0:
        _err(errors, "amount", "Must be greater than zero")
    if effective <= rec.start_date:
        _err(errors, "effective_date", "Must be after the start date. To change every occurrence, edit the amount.")
    elif rec.end_date is not None and effective > rec.end_date:
        _err(errors, "effective_date", "Must be on or before the end date")
    if errors:
        raise validation_error(errors)

    new = Recurrence(
        household_id=rec.household_id, type=rec.type, person_id=rec.person_id, amount=amount,
        currency=rec.currency, payment_method=rec.payment_method, card_id=rec.card_id,
        account_id=rec.account_id, category_id=rec.category_id, description=rec.description,
        interval_months=rec.interval_months, day_of_month=rec.day_of_month, start_date=effective,
        end_date=rec.end_date, skipped_dates=[d for d in rec.skipped_dates if d >= effective],
        is_active=rec.is_active, created_by_id=caller.id,
    )  # fmt: skip
    db.add(new)
    db.flush()
    rec.end_date = effective - timedelta(days=1)
    rec.skipped_dates = [d for d in rec.skipped_dates if d < effective]
    model = kind_of(rec.type).model
    db.execute(
        update(model)
        .where(model.recurrence_id == rec.id, model.occurrence_date >= effective)
        .values(recurrence_id=new.id)
    )
    db.flush()
    return new


def delete(db: Session, rec: Recurrence) -> None:
    model = kind_of(rec.type).model
    count = db.scalar(select(func.count()).select_from(model).where(model.recurrence_id == rec.id))
    if count:
        key = "expenses" if rec.type is EntryType.EXPENSE else "incomes"
        raise ApiError(
            409, "IN_USE", f"This fixed entry has {count} registered payment(s). End or pause it instead.",
            extra={"usage": {"expenses": 0, "incomes": 0, key: count}},
        )  # fmt: skip
    db.delete(rec)
    db.flush()


# --- Register and skip -------------------------------------------------------------


def register(
    db: Session, household: Household, caller: User, rec: Recurrence, occurrence: date, overrides: dict[str, Any],
    today: date,
):
    """Create the Expense/Income row for an occurrence (§12.2)."""
    _require_occurrence(rec, occurrence)
    if occurrence in (rec.skipped_dates or ()):
        raise ApiError(409, "CONFLICT", "This occurrence was skipped. Undo the skip to register it.")
    if occurrence in registered_rows(db, rec):
        raise ApiError(409, "CONFLICT", "This occurrence is already registered.")

    kind = kind_of(rec.type)
    errors: Errors = {}
    person_id = overrides.get("person_id") or rec.person_id
    entries._check_member(db, household.id, person_id, "person_id", errors)
    entries._check_category(db, kind, household.id, rec.category_id, errors)
    amount = overrides.get("amount") or rec.amount
    if amount <= 0:
        _err(errors, "amount", "Must be greater than zero")
    payment = entries._resolve_payment(
        db, kind, household.id, method=rec.payment_method,
        card_id=overrides.get("card_id") or rec.card_id,
        account_id=overrides.get("account_id") or (None if rec.payment_method in CARD_METHODS and kind.has_card else rec.account_id),
        installments=1, prefix="", errors=errors,
    )  # fmt: skip
    if errors:
        raise validation_error(errors)

    transaction_date = overrides.get("transaction_date") or default_purchase_date(rec, payment, occurrence, today)
    planned = entries._plan(kind, payment, transaction_date, amount, entries._holidays_for(db, transaction_date))[0]
    description = overrides["description"] if "description" in overrides else rec.description
    row = entries._new_row(
        kind, household.id, caller.id,
        person_id=person_id, transaction_date=transaction_date, payment_date=planned.payment_date,
        amount=amount, currency=rec.currency, payment_method=rec.payment_method,
        card_id=payment.card.id if payment.card else None, account_id=payment.account.id,
        category_id=rec.category_id, description=blank_to_none(description),
        recurrence_id=rec.id, occurrence_date=occurrence,
    )  # fmt: skip
    db.add(row)
    db.flush()
    return row


def default_purchase_date(rec: Recurrence, payment: entries.Payment, occurrence: date, today: date) -> date:
    """The transaction date of a registered occurrence when the client sends none. For a credit
    card fixed expense it is a purchase date inside the statement due on the occurrence date:
    today while that statement is open, otherwise the statement's nearest day."""
    if not (is_card_bill(rec) and payment.card is not None):
        return occurrence
    cycle = CardCycle(payment.card.best_buy_day, payment.card.due_day)
    first, last = purchase_window(statement_due_in(occurrence.year, occurrence.month, cycle), cycle)
    return max(first, min(today, last))


def skip(db: Session, rec: Recurrence, occurrence: date) -> None:
    _require_occurrence(rec, occurrence)
    if occurrence in registered_rows(db, rec):
        raise ApiError(409, "CONFLICT", "This occurrence is already registered. Delete the payment first.")
    if occurrence not in rec.skipped_dates:
        rec.skipped_dates = sorted([*rec.skipped_dates, occurrence])
        db.flush()


def unskip(db: Session, rec: Recurrence, occurrence: date) -> None:
    _require_occurrence(rec, occurrence)
    if occurrence in rec.skipped_dates:
        rec.skipped_dates = [d for d in rec.skipped_dates if d != occurrence]
        db.flush()
