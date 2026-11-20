"""Household creation and its seed data (specs/schemas.md §4.1, §9)."""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.enums import AccountType, Currency, EntryType
from app.models import Account, Category, Household

DEFAULT_EXPENSE_CATEGORIES: tuple[str, ...] = (
    "Food", "Gasoline", "Car", "House", "Rent", "Courses", "Music", "Clothes",
    "Health", "Pharmacy", "Gym", "Kids", "Trips", "Transport", "Entertainment",
    "Birthdays", "Gas", "Electricity", "Internet", "AI", "Storage", "Phone",
    "Business", "Tax", "Other",
)  # fmt: skip

CASH_ACCOUNT_NAME = "Cash"


def household_name_for(person_name: str) -> str:
    first_name = person_name.strip().split()[0]
    return f"{first_name}'s household"[:60]


def create_household(
    db: Session,
    *,
    person_name: str,
    today: date,
    default_currency: Currency = Currency.BRL,
) -> Household:
    """Create a household with its default expense categories and a Cash account.

    Used at signup without an invitation and when a member leaves or is removed
    (§4.2). Only flushes: the caller owns the transaction.
    """
    household = Household(name=household_name_for(person_name), default_currency=default_currency)
    db.add(household)
    db.flush()

    db.add_all(
        Category(household_id=household.id, type=EntryType.EXPENSE, name=name)
        for name in DEFAULT_EXPENSE_CATEGORIES
    )
    db.add(
        Account(
            household_id=household.id,
            type=AccountType.CASH,
            name=CASH_ACCOUNT_NAME,
            currency=default_currency,
            opening_balance=Decimal("0.00"),
            opening_balance_date=today,
        )
    )
    db.flush()
    return household
