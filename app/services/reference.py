"""Accounts, cards and categories (specs/schemas.md §7-§9, §18).

Services flush but never commit; routes own the transaction.
"""

import re
import uuid
from datetime import date
from decimal import Decimal
from typing import TypeVar

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import ApiError, validation_error
from app.domain.enums import AccountType, CardType, EntryType
from app.models import Account, Card, Category, Expense, Household, Income, Recurrence, Transfer, User
from app.schemas.common import blank_to_none
from app.services.recurrences import follow_card_due_day
from app.schemas.reference import (
    AccountCreate,
    AccountPatch,
    CardCreate,
    CardPatch,
    CategoryCreate,
    CategoryPatch,
)

M = TypeVar("M", Account, Card, Category)

ALIAS_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
LAST_FOUR_PATTERN = re.compile(r"\d{4}")


def get_owned(db: Session, model: type[M], household_id: uuid.UUID, record_id: uuid.UUID) -> M:
    """A household's record, or 404 (also for other households' ids, specs/api.md §1.2)."""
    record = db.get(model, record_id)
    if record is None or record.household_id != household_id:
        raise ApiError(404, "NOT_FOUND", f"{model.__name__} not found.")
    return record


def _count(db: Session, model, *conditions) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*conditions))


def _in_use(usage: dict[str, int], label: str) -> ApiError:
    total = sum(usage.values())
    return ApiError(
        409,
        "IN_USE",
        f"This {label} is used by {total} record(s). Archive it instead.",
        extra={"usage": usage},
    )


def _conflict(field: str, message: str) -> ApiError:
    return ApiError(409, "CONFLICT", message, fields={field: [message]})


def _flush_unique(db: Session, field: str, message: str) -> None:
    """Flush, turning a race on a unique index into a 409 for `field`."""
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        raise _conflict(field, message) from exc


def _list(db: Session, model, household_id: uuid.UUID, include_archived: bool, *conditions, order_by: tuple):
    stmt = select(model).where(model.household_id == household_id, *conditions)
    if not include_archived:
        stmt = stmt.where(model.is_active.is_(True))
    return list(db.scalars(stmt.order_by(*order_by)))


# --- Accounts (§7) -----------------------------------------------------------------


def list_accounts(db: Session, household_id: uuid.UUID, include_archived: bool) -> list[Account]:
    return _list(db, Account, household_id, include_archived, order_by=(Account.type, func.lower(Account.name)))


def _account_name_taken(db: Session, household_id: uuid.UUID, name: str, exclude: uuid.UUID | None = None) -> bool:
    stmt = select(Account.id).where(Account.household_id == household_id, func.lower(Account.name) == name.lower())
    if exclude is not None:
        stmt = stmt.where(Account.id != exclude)
    return db.scalar(stmt) is not None


ACCOUNT_NAME_TAKEN = "An account with this name already exists"


def create_account(db: Session, household: Household, body: AccountCreate, today: date) -> Account:
    if _account_name_taken(db, household.id, body.name):
        raise _conflict("name", ACCOUNT_NAME_TAKEN)
    account = Account(
        household_id=household.id,
        type=body.type,
        name=body.name,
        currency=body.currency or household.default_currency,
        opening_balance=body.opening_balance if body.opening_balance is not None else Decimal("0.00"),
        opening_balance_date=body.opening_balance_date or today,
        is_active=True,
    )
    db.add(account)
    _flush_unique(db, "name", ACCOUNT_NAME_TAKEN)
    return account


def update_account(db: Session, account: Account, body: AccountPatch) -> None:
    sent = body.model_fields_set
    errors: dict[str, list[str]] = {}
    if "type" in sent and body.type != account.type:
        errors["type"] = ["Can't be changed after creation"]
    for field in ("name", "currency", "opening_balance", "opening_balance_date"):
        if field in sent and getattr(body, field) is None:
            errors[field] = ["Can't be empty"]
    if errors:
        raise validation_error(errors)

    if "name" in sent and _account_name_taken(db, account.household_id, body.name, exclude=account.id):
        raise _conflict("name", ACCOUNT_NAME_TAKEN)
    for field in ("name", "currency", "opening_balance", "opening_balance_date"):
        if field in sent:
            setattr(account, field, getattr(body, field))
    _flush_unique(db, "name", ACCOUNT_NAME_TAKEN)


def adjust_account(db: Session, account: Account, balance: Decimal, on: date) -> None:
    """Reconcile with the real bank balance (§14.3)."""
    account.opening_balance = balance
    account.opening_balance_date = on
    db.flush()


def _active_cash_accounts(db: Session, household_id: uuid.UUID) -> int:
    return _count(
        db, Account, Account.household_id == household_id, Account.type == AccountType.CASH, Account.is_active.is_(True)
    )


def _guard_last_cash(db: Session, account: Account) -> None:
    if account.type is AccountType.CASH and account.is_active and _active_cash_accounts(db, account.household_id) <= 1:
        raise ApiError(422, "VALIDATION_ERROR", "The household needs at least one active cash account.")


def archive_account(db: Session, account: Account) -> None:
    _guard_last_cash(db, account)
    account.is_active = False
    db.flush()


def account_usage(db: Session, account: Account) -> dict[str, int]:
    return {
        "expenses": _count(db, Expense, Expense.account_id == account.id),
        "incomes": _count(db, Income, Income.account_id == account.id),
        "recurrences": _count(db, Recurrence, Recurrence.account_id == account.id),
        "cards": _count(db, Card, Card.account_id == account.id),
        "transfers": _count(db, Transfer, or_(Transfer.from_account_id == account.id, Transfer.to_account_id == account.id)),
    }


def delete_account(db: Session, account: Account) -> None:
    usage = account_usage(db, account)
    if any(usage.values()):
        raise _in_use(usage, "account")
    _guard_last_cash(db, account)
    db.delete(account)
    db.flush()


# --- Cards (§8) --------------------------------------------------------------------

CARD_ALIAS_TAKEN = "A card with this alias already exists"


def list_cards(db: Session, household_id: uuid.UUID, include_archived: bool) -> list[Card]:
    return _list(db, Card, household_id, include_archived, order_by=(func.lower(Card.alias),))


def _validate_card(
    db: Session,
    household_id: uuid.UUID,
    *,
    owner_id: uuid.UUID,
    alias: str,
    card_type: CardType,
    account_id: uuid.UUID,
    last_four: str | None,
    best_buy_day: int | None,
    due_day: int | None,
    exclude: uuid.UUID | None,
    check_owner: bool,
    check_account: bool,
) -> None:
    """Validate a card's final state (after a create or a patch)."""
    errors: dict[str, list[str]] = {}
    if not ALIAS_PATTERN.fullmatch(alias):
        errors["alias"] = ["Must be a single word: letters, digits, - and _"]
    if last_four is not None and not LAST_FOUR_PATTERN.fullmatch(last_four):
        errors["last_four"] = ["Must be exactly 4 digits"]
    if card_type.has_credit:
        for field, value in (("best_buy_day", best_buy_day), ("due_day", due_day)):
            if value is None:
                errors[field] = ["Required for credit cards"]
    else:
        for field, value in (("best_buy_day", best_buy_day), ("due_day", due_day)):
            if value is not None:
                errors[field] = ["Must be empty for debit-only cards"]
    if check_owner:
        owner = db.get(User, owner_id)
        if owner is None or owner.household_id != household_id:
            errors["owner_id"] = ["Must be a current member of the household"]
    if check_account:
        account = db.get(Account, account_id)
        if account is None or account.household_id != household_id:
            errors["account_id"] = ["Account not found"]
        elif account.type is not AccountType.BANK:
            errors["account_id"] = ["Must be a bank account"]
        elif not account.is_active:
            errors["account_id"] = ["Account is archived"]
    if errors:
        raise validation_error(errors)

    stmt = select(Card.id).where(Card.household_id == household_id, func.lower(Card.alias) == alias.lower())
    if exclude is not None:
        stmt = stmt.where(Card.id != exclude)
    if db.scalar(stmt) is not None:
        raise _conflict("alias", CARD_ALIAS_TAKEN)


def create_card(db: Session, household_id: uuid.UUID, caller: User, body: CardCreate) -> Card:
    owner_id = body.owner_id or caller.id
    last_four = blank_to_none(body.last_four)
    _validate_card(
        db, household_id, owner_id=owner_id, alias=body.alias, card_type=body.type, account_id=body.account_id,
        last_four=last_four, best_buy_day=body.best_buy_day, due_day=body.due_day, exclude=None,
        check_owner=True, check_account=True,
    )  # fmt: skip
    card = Card(
        household_id=household_id, owner_id=owner_id, alias=body.alias, type=body.type,
        account_id=body.account_id, last_four=last_four, best_buy_day=body.best_buy_day,
        due_day=body.due_day, is_active=True,
    )  # fmt: skip
    db.add(card)
    _flush_unique(db, "alias", CARD_ALIAS_TAKEN)
    return card


def update_card(db: Session, card: Card, body: CardPatch) -> None:
    sent = body.model_fields_set
    for field in ("owner_id", "alias", "type", "account_id"):
        if field in sent and getattr(body, field) is None:
            raise validation_error({field: ["Can't be empty"]})
    final = {
        field: (getattr(body, field) if field in sent else getattr(card, field))
        for field in ("owner_id", "alias", "type", "account_id", "last_four", "best_buy_day", "due_day")
    }
    final["last_four"] = blank_to_none(final["last_four"])
    _validate_card(
        db, card.household_id, owner_id=final["owner_id"], alias=final["alias"], card_type=final["type"],
        account_id=final["account_id"], last_four=final["last_four"], best_buy_day=final["best_buy_day"],
        due_day=final["due_day"], exclude=card.id,
        # Only re-check references that change, so an unrelated edit doesn't fail
        # because the owner left or the account was archived later.
        check_owner="owner_id" in sent, check_account="account_id" in sent,
    )  # fmt: skip
    old_due_day = card.due_day
    for field, value in final.items():
        setattr(card, field, value)
    _flush_unique(db, "alias", CARD_ALIAS_TAKEN)
    follow_card_due_day(db, card, old_due_day)


def unarchive_card(db: Session, card: Card) -> None:
    owner = db.get(User, card.owner_id)
    if owner is None or owner.household_id != card.household_id:
        raise validation_error(
            {"owner_id": ["The owner is a former member. Assign a current member first."]}
        )
    card.is_active = True
    db.flush()


def card_usage(db: Session, card: Card) -> dict[str, int]:
    return {
        "expenses": _count(db, Expense, Expense.card_id == card.id),
        "incomes": 0,
        "recurrences": _count(db, Recurrence, Recurrence.card_id == card.id),
    }


def delete_card(db: Session, card: Card) -> None:
    usage = card_usage(db, card)
    if any(usage.values()):
        raise _in_use(usage, "card")
    db.delete(card)
    db.flush()


# --- Categories (§9) ---------------------------------------------------------------

CATEGORY_NAME_TAKEN = "A category with this name already exists"


def list_categories(db: Session, household_id: uuid.UUID, entry_type: EntryType, include_archived: bool) -> list[Category]:
    return _list(
        db, Category, household_id, include_archived, Category.type == entry_type,
        order_by=(func.lower(Category.name),),
    )  # fmt: skip


def _category_name_taken(db: Session, household_id, entry_type, name, exclude=None) -> bool:
    stmt = select(Category.id).where(
        Category.household_id == household_id,
        Category.type == entry_type,
        func.lower(Category.name) == name.lower(),
    )
    if exclude is not None:
        stmt = stmt.where(Category.id != exclude)
    return db.scalar(stmt) is not None


def create_category(db: Session, household_id: uuid.UUID, body: CategoryCreate) -> Category:
    if _category_name_taken(db, household_id, body.type, body.name):
        raise _conflict("name", CATEGORY_NAME_TAKEN)
    category = Category(household_id=household_id, type=body.type, name=body.name, is_active=True)
    db.add(category)
    _flush_unique(db, "name", CATEGORY_NAME_TAKEN)
    return category


def update_category(db: Session, category: Category, body: CategoryPatch) -> None:
    if "name" not in body.model_fields_set:
        return
    if body.name is None:
        raise validation_error({"name": ["Can't be empty"]})
    if _category_name_taken(db, category.household_id, category.type, body.name, exclude=category.id):
        raise _conflict("name", CATEGORY_NAME_TAKEN)
    if body.name != category.name:
        category.seed_key = None  # the user's own name wins over the translated one
    category.name = body.name
    _flush_unique(db, "name", CATEGORY_NAME_TAKEN)


def category_usage(db: Session, category: Category) -> dict[str, int]:
    return {
        "expenses": _count(db, Expense, Expense.category_id == category.id),
        "incomes": _count(db, Income, Income.category_id == category.id),
        "recurrences": _count(db, Recurrence, Recurrence.category_id == category.id),
    }


def delete_category(db: Session, category: Category) -> None:
    usage = category_usage(db, category)
    if any(usage.values()):
        raise _in_use(usage, "category")
    db.delete(category)
    db.flush()


def set_active(db: Session, record: Account | Card | Category, active: bool) -> None:
    record.is_active = active
    db.flush()

