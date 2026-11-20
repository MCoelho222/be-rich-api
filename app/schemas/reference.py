"""Accounts, cards and categories (specs/api.md §7-§9)."""

import datetime as dt
import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, Field

from app.domain.enums import AccountType, CardType, Currency, EntryType
from app.schemas.common import MoneyIn, MoneyOut, OrmModel, Text

Day = Annotated[int, Field(ge=1, le=31)]


# --- Accounts ----------------------------------------------------------------------


class AccountOut(OrmModel):
    id: uuid.UUID
    type: AccountType
    name: str
    currency: Currency
    opening_balance: MoneyOut
    opening_balance_date: date
    is_active: bool
    created_at: datetime
    updated_at: datetime


class AccountCreate(BaseModel):
    type: AccountType = AccountType.BANK
    name: Text(40, min_length=1)
    currency: Currency | None = None  # default: the household's currency
    opening_balance: MoneyIn | None = None  # default: 0.00
    opening_balance_date: date | None = None  # default: today


class AccountPatch(BaseModel):
    type: AccountType | None = None  # rejected: can't change after creation
    name: Text(40, min_length=1) | None = None
    currency: Currency | None = None
    opening_balance: MoneyIn | None = None
    opening_balance_date: date | None = None


class AccountAdjust(BaseModel):
    balance: MoneyIn
    date: dt.date | None = None  # default: today


# --- Cards -------------------------------------------------------------------------


class CardOut(OrmModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    alias: str
    type: CardType
    account_id: uuid.UUID
    last_four: str | None
    best_buy_day: int | None
    due_day: int | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CardCreate(BaseModel):
    owner_id: uuid.UUID | None = None  # default: the caller
    alias: Text(20, min_length=1)
    type: CardType = CardType.CREDIT
    account_id: uuid.UUID
    last_four: Text(4) | None = None
    best_buy_day: Day | None = None
    due_day: Day | None = None


class CardPatch(BaseModel):
    owner_id: uuid.UUID | None = None
    alias: Text(20, min_length=1) | None = None
    type: CardType | None = None
    account_id: uuid.UUID | None = None
    last_four: Text(4) | None = None
    best_buy_day: Day | None = None
    due_day: Day | None = None


class CardPreviewIn(BaseModel):
    best_buy_day: Day
    due_day: Day
    purchase_date: date | None = None  # default: today


class CardPreviewOut(BaseModel):
    closing_date: date
    payment_date: date


# --- Categories --------------------------------------------------------------------


class CategoryOut(OrmModel):
    id: uuid.UUID
    type: EntryType
    name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CategoryCreate(BaseModel):
    type: EntryType
    name: Text(30, min_length=1)


class CategoryPatch(BaseModel):
    name: Text(30, min_length=1) | None = None
