"""Expenses and incomes (specs/schemas.md §10-§11, specs/api.md §10-§11).

One implementation serves both entry types; `Kind` captures the differences
(person field, whether cards exist, the credit payment-date rule).
Services flush but never commit; routes own the transaction.
"""

import base64
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select, tuple_
from sqlalchemy.orm import Session

from app.api.errors import ApiError, validation_error
from app.domain.credit import CardCycle
from app.domain.enums import CARD_METHODS, AccountType, Currency, EditScope, EntryType, PaymentMethod
from app.domain.payments import PlannedRow, plan_rows
from app.models import Account, Card, Category, Expense, Household, Income, User
from app.schemas.common import blank_to_none
from app.services.calendar import load_holidays

Row = Expense | Income
MAX_SERIES_YEARS = 6  # 60 monthly installments + up to ~2 months for a credit due date


@dataclass(frozen=True)
class Kind:
    entry_type: EntryType
    model: type[Expense] | type[Income]
    person_field: str  # "spender_id" or "receiver_id"

    @property
    def has_card(self) -> bool:
        return self.entry_type is EntryType.EXPENSE

    @property
    def label(self) -> str:
        return self.entry_type.value.lower()


EXPENSE = Kind(EntryType.EXPENSE, Expense, "spender_id")
INCOME = Kind(EntryType.INCOME, Income, "receiver_id")

Errors = dict[str, list[str]]


def _err(errors: Errors, field: str, message: str) -> None:
    errors.setdefault(field, []).append(message)


# --- Reference checks --------------------------------------------------------------


def _check_member(db: Session, household_id: uuid.UUID, user_id: uuid.UUID, field: str, errors: Errors) -> None:
    user = db.get(User, user_id)
    if user is None or user.household_id != household_id:
        _err(errors, field, "Must be a current member of the household")


def _check_category(db: Session, kind: Kind, household_id: uuid.UUID, category_id: uuid.UUID, errors: Errors) -> None:
    category = db.get(Category, category_id)
    if category is None or category.household_id != household_id:
        _err(errors, "category_id", "Category not found")
    elif category.type is not kind.entry_type:
        _err(errors, "category_id", f"Must be an {kind.label} category")
    elif not category.is_active:
        _err(errors, "category_id", "Category is archived")


def _first_cash_account(db: Session, household_id: uuid.UUID) -> Account | None:
    return db.scalar(
        select(Account)
        .where(Account.household_id == household_id, Account.type == AccountType.CASH, Account.is_active.is_(True))
        .order_by(Account.created_at, Account.id)
        .limit(1)
    )


@dataclass
class Payment:
    method: PaymentMethod
    card: Card | None
    account: Account | None
    installments: int


def _resolve_payment(
    db: Session,
    kind: Kind,
    household_id: uuid.UUID,
    *,
    method: PaymentMethod,
    card_id: uuid.UUID | None,
    account_id: uuid.UUID | None,
    installments: int,
    prefix: str,
    errors: Errors,
) -> Payment:
    """Validate a payment's method, card and account (§10, §11) and resolve the account."""
    card: Card | None = None
    account: Account | None = None
    if kind.has_card and method is PaymentMethod.DEBIT and installments != 1:
        _err(errors, prefix + "installments", "Debit payments can't have installments")

    if kind.has_card and method in CARD_METHODS:
        if card_id is None:
            _err(errors, prefix + "card_id", "Required for credit and debit payments")
        else:
            card = db.get(Card, card_id)
            if card is None or card.household_id != household_id:
                _err(errors, prefix + "card_id", "Card not found")
                card = None
            elif not card.is_active:
                _err(errors, prefix + "card_id", "Card is archived")
            elif not card.type.supports(method):
                _err(errors, prefix + "card_id", f"This card can't be used for {method.value.lower()}")
            else:
                account = db.get(Account, card.account_id)
                if account is None or not account.is_active:
                    _err(errors, prefix + "card_id", "The card's paying account is archived")
        return Payment(method, card, account, installments)

    if card_id is not None:
        _err(errors, prefix + "card_id", "Only for credit and debit payments")
    wanted = AccountType.CASH if method is PaymentMethod.CASH else AccountType.BANK
    if account_id is None:
        if wanted is AccountType.CASH:
            account = _first_cash_account(db, household_id)
            if account is None:
                _err(errors, prefix + "account_id", "No active cash account")
        else:
            _err(errors, prefix + "account_id", "Required for this payment method")
    else:
        account = db.get(Account, account_id)
        if account is None or account.household_id != household_id:
            _err(errors, prefix + "account_id", "Account not found")
            account = None
        elif account.type is not wanted:
            _err(errors, prefix + "account_id", f"Must be a {wanted.value.lower()} account")
        elif not account.is_active:
            _err(errors, prefix + "account_id", "Account is archived")
    return Payment(method, None, account, installments)


def _plan(
    kind: Kind, payment: Payment, transaction_date: date, total: Decimal, holidays: set[date]
) -> list[PlannedRow]:
    cycle = None
    if payment.method is PaymentMethod.CREDIT and payment.card is not None:
        cycle = CardCycle(payment.card.best_buy_day, payment.card.due_day)
    return plan_rows(kind.entry_type, payment.method, transaction_date, total, payment.installments, holidays, cycle)


def _holidays_for(db: Session, transaction_date: date) -> set[date]:
    return load_holidays(db, transaction_date.year, transaction_date.year + MAX_SERIES_YEARS)


# --- Create ------------------------------------------------------------------------


@dataclass
class PlannedPart:
    payment: Payment
    rows: list[PlannedRow]


@dataclass
class PurchasePlan:
    transaction_date: date
    currency: Currency
    person_id: uuid.UUID
    category_id: uuid.UUID
    description: str | None
    parts: list[PlannedPart]

    @property
    def total(self) -> Decimal:
        return sum((r.amount for p in self.parts for r in p.rows), Decimal("0"))


def plan_purchase(db: Session, kind: Kind, household: Household, caller: User, body: Any, today: date) -> PurchasePlan:
    """Validate a create body and compute every row it produces (§10.1-§10.5)."""
    errors: Errors = {}
    transaction_date = body.transaction_date or today
    currency = body.currency or household.default_currency
    person_id = getattr(body, kind.person_field) or caller.id
    _check_member(db, household.id, person_id, kind.person_field, errors)
    _check_category(db, kind, household.id, body.category_id, errors)

    total = body.total_amount
    if total <= 0:
        _err(errors, "total_amount", "Must be greater than zero")
    parts = body.parts
    amounts: list[Decimal | None] = [p.amount for p in parts]
    if len(parts) == 1:
        if amounts[0] is None:
            amounts[0] = total
        elif amounts[0] != total:
            _err(errors, "parts[0].amount", "Must equal total_amount (or be omitted)")
    else:
        for i, amount in enumerate(amounts):
            if amount is None:
                _err(errors, f"parts[{i}].amount", "Required when paying with more than one method")
        if all(a is not None for a in amounts) and sum(amounts) != total:
            _err(errors, "parts", "The parts must add up to total_amount")
    for i, amount in enumerate(amounts):
        if amount is not None and amount <= 0:
            _err(errors, f"parts[{i}].amount", "Must be greater than zero")

    payments = [
        _resolve_payment(
            db, kind, household.id, method=p.payment_method, card_id=getattr(p, "card_id", None),
            account_id=p.account_id, installments=p.installments, prefix=f"parts[{i}].", errors=errors,
        )  # fmt: skip
        for i, p in enumerate(parts)
    ]
    if errors:
        raise validation_error(errors)

    holidays = _holidays_for(db, transaction_date)
    planned: list[PlannedPart] = []
    for i, (payment, amount) in enumerate(zip(payments, amounts, strict=True)):
        try:
            rows = _plan(kind, payment, transaction_date, amount, holidays)
        except ValueError as exc:
            _err(errors, f"parts[{i}].installments", str(exc).capitalize())
            continue
        planned.append(PlannedPart(payment, rows))
    if errors:
        raise validation_error(errors)

    return PurchasePlan(
        transaction_date, currency, person_id, body.category_id, blank_to_none(body.description), planned
    )


def _new_row(kind: Kind, household_id: uuid.UUID, created_by: uuid.UUID, **values: Any) -> Row:
    person_id = values.pop("person_id")
    if not kind.has_card:
        values.pop("card_id", None)
    return kind.model(household_id=household_id, created_by_id=created_by, **{kind.person_field: person_id}, **values)


def create_purchase(db: Session, kind: Kind, household: Household, caller: User, plan: PurchasePlan) -> tuple[uuid.UUID | None, list[Row]]:
    split_group_id = uuid.uuid4() if len(plan.parts) > 1 else None
    rows: list[Row] = []
    for part in plan.parts:
        group_id = uuid.uuid4() if part.payment.installments > 1 else None
        for planned in part.rows:
            rows.append(
                _new_row(
                    kind, household.id, caller.id,
                    person_id=plan.person_id, transaction_date=plan.transaction_date,
                    payment_date=planned.payment_date, amount=planned.amount, currency=plan.currency,
                    payment_method=part.payment.method, card_id=part.payment.card.id if part.payment.card else None,
                    account_id=part.payment.account.id, category_id=plan.category_id,
                    description=plan.description, installment_number=planned.installment_number,
                    installment_total=planned.installment_total, installment_group_id=group_id,
                    split_group_id=split_group_id,
                )  # fmt: skip
            )
    db.add_all(rows)
    db.flush()
    return split_group_id, rows


# --- Read --------------------------------------------------------------------------


def get_row(db: Session, kind: Kind, household_id: uuid.UUID, row_id: uuid.UUID) -> Row:
    row = db.get(kind.model, row_id)
    if row is None or row.household_id != household_id:
        raise ApiError(404, "NOT_FOUND", f"{kind.entry_type.value.capitalize()} not found.")
    return row


def _part_rows(db: Session, kind: Kind, row: Row) -> list[Row]:
    """The rows of the payment part `row` belongs to: its installment series, or itself."""
    if row.installment_group_id is None:
        return [row]
    model = kind.model
    return list(
        db.scalars(
            select(model)
            .where(model.installment_group_id == row.installment_group_id)
            .order_by(model.installment_number)
        )
    )


def _split_rows(db: Session, kind: Kind, row: Row) -> list[Row]:
    if row.split_group_id is None:
        return _part_rows(db, kind, row)
    model = kind.model
    return list(
        db.scalars(
            select(model)
            .where(model.split_group_id == row.split_group_id)
            .order_by(model.payment_method, model.installment_group_id, model.installment_number, model.id)
        )
    )


@dataclass(frozen=True)
class ListFilters:
    start: date | None = None
    end: date | None = None
    date_field: str = "payment_date"
    account_id: uuid.UUID | None = None
    card_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    person_id: uuid.UUID | None = None
    payment_method: PaymentMethod | None = None
    recurrence_id: uuid.UUID | None = None
    fixed_only: bool = False
    installment_group_id: uuid.UUID | None = None
    split_group_id: uuid.UUID | None = None
    q: str | None = None


def _encode_cursor(row: Row, date_field: str) -> str:
    raw = json.dumps([getattr(row, date_field).isoformat(), row.created_at.isoformat(), str(row.id)])
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[date, datetime, uuid.UUID]:
    try:
        day, created, row_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return date.fromisoformat(day), datetime.fromisoformat(created), uuid.UUID(row_id)
    except (ValueError, TypeError) as exc:
        raise ApiError(400, "BAD_REQUEST", "Invalid cursor.") from exc


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_rows(
    db: Session, kind: Kind, household_id: uuid.UUID, filters: ListFilters, limit: int, cursor: str | None
) -> tuple[list[Row], str | None]:
    model = kind.model
    day_col = getattr(model, filters.date_field)
    stmt: Select = select(model).where(model.household_id == household_id)
    if filters.start:
        stmt = stmt.where(day_col >= filters.start)
    if filters.end:
        stmt = stmt.where(day_col <= filters.end)
    simple = {
        "account_id": filters.account_id,
        "category_id": filters.category_id,
        kind.person_field: filters.person_id,
        "payment_method": filters.payment_method,
        "recurrence_id": filters.recurrence_id,
        "installment_group_id": filters.installment_group_id,
        "split_group_id": filters.split_group_id,
    }
    if kind.has_card:
        simple["card_id"] = filters.card_id
    for column, value in simple.items():
        if value is not None:
            stmt = stmt.where(getattr(model, column) == value)
    if filters.fixed_only:
        stmt = stmt.where(model.recurrence_id.is_not(None))
    if filters.q:
        stmt = stmt.where(func.lower(model.description).like(f"%{_escape_like(filters.q.lower())}%", escape="\\"))
    if cursor:
        day, created, row_id = _decode_cursor(cursor)
        stmt = stmt.where(tuple_(day_col, model.created_at, model.id) < tuple_(day, created, row_id))
    stmt = stmt.order_by(day_col.desc(), model.created_at.desc(), model.id.desc()).limit(limit + 1)
    rows = list(db.scalars(stmt))
    next_cursor = _encode_cursor(rows[limit - 1], filters.date_field) if len(rows) > limit else None
    return rows[:limit], next_cursor


# --- Update and delete (§10.6) -----------------------------------------------------

PAYMENT_FIELDS = ("transaction_date", "payment_method", "card_id", "account_id", "currency", "installments")
REQUIRED_FIELDS = ("person_id", "category_id", "amount", "transaction_date", "payment_method", "currency", "installments")
SHARED_SPLIT_FIELDS = ("person_id", "category_id", "description")


def _scope_rows(part: Sequence[Row], row: Row, scope: EditScope) -> list[Row]:
    if scope is EditScope.THIS:
        return [row]
    if scope is EditScope.THIS_AND_FOLLOWING:
        return [r for r in part if r.installment_number >= row.installment_number]
    return list(part)


def _require_scope(row: Row, scope: EditScope | None) -> EditScope:
    if row.installment_group_id is None:
        return EditScope.ALL  # a single row: every change applies to the whole "series" of one
    if scope is None:
        raise ApiError(
            422, "SCOPE_REQUIRED",
            "This row is part of an installment series: choose scope THIS, THIS_AND_FOLLOWING or ALL.",
        )  # fmt: skip
    return scope


def _apply_plan(
    db: Session, kind: Kind, part: list[Row], plan: list[PlannedRow], payment: Payment, transaction_date: date, currency: Currency
) -> None:
    """Rewrite a part's rows to match `plan`, updating rows in place so ids stay
    stable, inserting extra installments and deleting surplus ones."""
    template = part[0]
    existing_group = next((r.installment_group_id for r in part if r.installment_group_id), None)
    group_id = (existing_group or uuid.uuid4()) if len(plan) > 1 else None
    for i, planned in enumerate(plan):
        if i < len(part):
            target = part[i]
        else:
            target = _new_row(
                kind, template.household_id, template.created_by_id,
                person_id=getattr(template, kind.person_field), category_id=template.category_id,
                description=template.description, split_group_id=template.split_group_id,
                transaction_date=transaction_date, payment_date=planned.payment_date, amount=planned.amount,
                currency=currency, payment_method=payment.method, account_id=payment.account.id,
                card_id=payment.card.id if payment.card else None,
            )  # fmt: skip
            db.add(target)
        target.transaction_date = transaction_date
        target.payment_date = planned.payment_date
        target.amount = planned.amount
        target.currency = currency
        target.payment_method = payment.method
        target.account_id = payment.account.id
        if kind.has_card:
            target.card_id = payment.card.id if payment.card else None
        target.installment_number = planned.installment_number
        target.installment_total = planned.installment_total
        target.installment_group_id = group_id
    for surplus in part[len(plan):]:
        db.delete(surplus)


def _existing_payment(db: Session, kind: Kind, part: list[Row]) -> Payment:
    """The current payment of a part, without re-validating it (archived references
    are fine when the payment itself isn't being changed)."""
    first = part[0]
    card = db.get(Card, first.card_id) if kind.has_card and first.card_id else None
    return Payment(first.payment_method, card, db.get(Account, first.account_id), first.installment_total)


def update_entry(
    db: Session, kind: Kind, household: Household, row: Row, changes: dict[str, Any], scope: EditScope | None
) -> list[Row]:
    """Apply a PATCH (§10.6). Returns every row of the affected series or split purchase."""
    scope = _require_scope(row, scope)
    errors: Errors = {}
    for field in REQUIRED_FIELDS:
        if field in changes and changes[field] is None:
            _err(errors, kind.person_field if field == "person_id" else field, "Can't be empty")
    if errors:
        raise validation_error(errors)

    payment_changes = [f for f in PAYMENT_FIELDS if f in changes]
    if scope is not EditScope.ALL and payment_changes:
        raise validation_error({f: ["Can only be changed with scope ALL"] for f in payment_changes})
    if "person_id" in changes:
        _check_member(db, household.id, changes["person_id"], kind.person_field, errors)
    if "category_id" in changes:
        _check_category(db, kind, household.id, changes["category_id"], errors)
    if "amount" in changes and changes["amount"] <= 0:
        _err(errors, "amount", "Must be greater than zero")
    if row.recurrence_id is not None and changes.get("installments", 1) != 1:
        _err(errors, "installments", "A registered fixed-entry payment is a single row")
    if errors:
        raise validation_error(errors)

    part = _part_rows(db, kind, row)
    in_split = row.split_group_id is not None
    whole = _split_rows(db, kind, row) if in_split else part

    # Purchase-level fields: in a split purchase they stay identical on every row (§10.5).
    attribute = {"person_id": kind.person_field, "category_id": "category_id", "description": "description"}
    for field in SHARED_SPLIT_FIELDS:
        if field in changes:
            value = blank_to_none(changes[field]) if field == "description" else changes[field]
            for target in whole if in_split else _scope_rows(part, row, scope):
                setattr(target, attribute[field], value)

    regenerate = bool(payment_changes) or (scope is EditScope.ALL and "amount" in changes)
    if regenerate:
        _regenerate_part(db, kind, household, row, part, changes, errors)
        if in_split and ("transaction_date" in changes or "currency" in changes):
            _realign_split(db, kind, row, whole, changes)
    elif "amount" in changes:
        for target in _scope_rows(part, row, scope):
            target.amount = changes["amount"]
    db.flush()
    # `row` may have been deleted (fewer installments); the part's first row never is.
    anchor = part[0]
    return _split_rows(db, kind, anchor) if in_split else _part_rows(db, kind, anchor)


def _regenerate_part(
    db: Session, kind: Kind, household: Household, row: Row, part: list[Row], changes: dict[str, Any], errors: Errors
) -> None:
    current = _existing_payment(db, kind, part)
    method = changes.get("payment_method", current.method)
    installments = changes.get("installments", current.installments)
    transaction_date = changes.get("transaction_date", row.transaction_date)
    currency = changes.get("currency", row.currency)
    total = changes.get("amount", sum((r.amount for r in part), Decimal("0")))

    if any(f in changes for f in ("payment_method", "card_id", "account_id", "installments")):
        is_card = kind.has_card and method in CARD_METHODS
        card_id = changes.get("card_id", current.card.id if (is_card and current.card) else None)
        # Carry the current account over only if the new method needs the same kind
        # of account (cash stays cash, bank stays bank); otherwise it must be sent.
        same_account_kind = (
            not is_card
            and not (kind.has_card and current.method in CARD_METHODS)
            and (method is PaymentMethod.CASH) == (current.method is PaymentMethod.CASH)
        )
        account_id = changes.get("account_id", current.account.id if same_account_kind else None)
        payment = _resolve_payment(
            db, kind, household.id, method=method, card_id=card_id, account_id=account_id,
            installments=installments, prefix="", errors=errors,
        )  # fmt: skip
    else:
        payment = Payment(current.method, current.card, current.account, installments)
    if errors:
        raise validation_error(errors)
    try:
        plan = _plan(kind, payment, transaction_date, total, _holidays_for(db, transaction_date))
    except ValueError as exc:
        raise validation_error({"installments": [str(exc).capitalize()]}) from exc
    _apply_plan(db, kind, part, plan, payment, transaction_date, currency)


def _realign_split(db: Session, kind: Kind, row: Row, whole: list[Row], changes: dict[str, Any]) -> None:
    """Give every other part of a split purchase the new date/currency (§10.5),
    recomputing their payment dates."""
    transaction_date = changes.get("transaction_date", row.transaction_date)
    currency = changes.get("currency", row.currency)
    holidays = _holidays_for(db, transaction_date)
    edited_ids = {r.id for r in _part_rows(db, kind, row)}
    seen: set[Any] = set()
    for other in whole:
        key = other.installment_group_id or other.id
        if other.id in edited_ids or key in seen:
            continue
        seen.add(key)
        part = _part_rows(db, kind, other)
        payment = _existing_payment(db, kind, part)
        total = sum((r.amount for r in part), Decimal("0"))
        _apply_plan(db, kind, part, _plan(kind, payment, transaction_date, total, holidays), payment, transaction_date, currency)


def delete_entry(db: Session, kind: Kind, row: Row, scope: EditScope | None) -> int:
    """Delete by scope (§10.6). Remaining installments are not renumbered."""
    scope = _require_scope(row, scope)
    targets = _scope_rows(_part_rows(db, kind, row), row, scope)
    for target in targets:
        db.delete(target)
    db.flush()
    return len(targets)
