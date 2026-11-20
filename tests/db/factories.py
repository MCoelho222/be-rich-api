"""Minimal builders for database tests."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import AccountType, CardType, Currency, EntryType, PaymentMethod
from app.models import Account, Card, Category, Expense, Household, User
from app.services.households import create_household

TODAY = date(2026, 11, 20)


def make_household(db: Session, name: str = "Marcelo Coelho") -> Household:
    return create_household(db, person_name=name, today=TODAY)


def make_user(db: Session, household: Household, email: str | None = None, **fields) -> User:
    user = User(
        household_id=household.id,
        name=fields.pop("name", "Marcelo Coelho"),
        email=email or f"{uuid.uuid4().hex[:10]}@example.com",
        password_hash="argon2-hash-placeholder",
        **fields,
    )
    db.add(user)
    db.flush()
    return user


def make_bank_account(db: Session, household: Household, name: str = "Nubank") -> Account:
    account = Account(
        household_id=household.id,
        type=AccountType.BANK,
        name=name,
        currency=Currency.BRL,
        opening_balance_date=TODAY,
    )
    db.add(account)
    db.flush()
    return account


def make_card(db: Session, household: Household, owner: User, account: Account, **fields) -> Card:
    card = Card(
        household_id=household.id,
        owner_id=owner.id,
        account_id=account.id,
        alias=fields.pop("alias", "Nubank"),
        type=fields.pop("type", CardType.CREDIT),
        best_buy_day=fields.pop("best_buy_day", 25),
        due_day=fields.pop("due_day", 5),
        **fields,
    )
    db.add(card)
    db.flush()
    return card


def expense_category(db: Session, household: Household, name: str = "Food") -> Category:
    return db.scalars(
        select(Category).where(
            Category.household_id == household.id,
            Category.type == EntryType.EXPENSE,
            Category.name == name,
        )
    ).one()


def cash_account(db: Session, household: Household) -> Account:
    return db.scalars(
        select(Account).where(Account.household_id == household.id, Account.type == AccountType.CASH)
    ).one()


def make_expense(db: Session, household: Household, user: User, **fields) -> Expense:
    expense = Expense(
        household_id=household.id,
        spender_id=user.id,
        created_by_id=user.id,
        transaction_date=TODAY,
        payment_date=fields.pop("payment_date", TODAY),
        amount=fields.pop("amount", Decimal("10.00")),
        currency=Currency.BRL,
        payment_method=fields.pop("payment_method", PaymentMethod.CASH),
        account_id=fields.pop("account_id", None) or cash_account(db, household).id,
        category_id=expense_category(db, household).id,
        **fields,
    )
    db.add(expense)
    db.flush()
    return expense
