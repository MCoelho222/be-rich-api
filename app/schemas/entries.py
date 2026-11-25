"""Expense and income bodies (specs/api.md §10-§11)."""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, Field

from app.domain.enums import Currency, PaymentMethod
from app.schemas.common import MoneyIn, MoneyOut, OrmModel, Text

Installments = Annotated[int, Field(ge=1, le=60)]


class MoneyObj(BaseModel):
    amount: MoneyOut
    currency: Currency


# --- Create ------------------------------------------------------------------------


class ExpensePartIn(BaseModel):
    payment_method: PaymentMethod
    card_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    amount: MoneyIn | None = None
    installments: Installments = 1


class IncomePartIn(BaseModel):
    payment_method: PaymentMethod
    account_id: uuid.UUID | None = None
    amount: MoneyIn | None = None
    installments: Installments = 1


class _CreateBase(BaseModel):
    transaction_date: date | None = None  # default: today
    currency: Currency | None = None  # default: household currency
    category_id: uuid.UUID
    description: Text(200) | None = None
    total_amount: MoneyIn


class ExpenseCreate(_CreateBase):
    spender_id: uuid.UUID | None = None  # default: the caller
    parts: Annotated[list[ExpensePartIn], Field(min_length=1, max_length=6)]


class IncomeCreate(_CreateBase):
    receiver_id: uuid.UUID | None = None
    parts: Annotated[list[IncomePartIn], Field(min_length=1, max_length=6)]


# --- Update ------------------------------------------------------------------------


class _PatchBase(BaseModel):
    category_id: uuid.UUID | None = None
    description: Text(200) | None = None
    amount: MoneyIn | None = None
    # Only with scope=ALL (or on rows that aren't part of a series)
    transaction_date: date | None = None
    payment_method: PaymentMethod | None = None
    account_id: uuid.UUID | None = None
    currency: Currency | None = None
    installments: Installments | None = None


class ExpensePatch(_PatchBase):
    spender_id: uuid.UUID | None = None
    card_id: uuid.UUID | None = None


class IncomePatch(_PatchBase):
    receiver_id: uuid.UUID | None = None


# --- Output ------------------------------------------------------------------------


class _RowOut(OrmModel):
    id: uuid.UUID
    transaction_date: date
    payment_date: date
    amount: MoneyOut
    currency: Currency
    payment_method: PaymentMethod
    account_id: uuid.UUID
    category_id: uuid.UUID
    description: str | None
    installment_number: int
    installment_total: int
    installment_group_id: uuid.UUID | None
    split_group_id: uuid.UUID | None
    recurrence_id: uuid.UUID | None
    occurrence_date: date | None
    created_by_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ExpenseOut(_RowOut):
    spender_id: uuid.UUID
    card_id: uuid.UUID | None


class IncomeOut(_RowOut):
    receiver_id: uuid.UUID


class PlannedRowOut(BaseModel):
    """A row a create would produce (no ids are assigned in a preview)."""

    part: int
    transaction_date: date
    payment_date: date
    amount: MoneyOut
    currency: Currency
    payment_method: PaymentMethod
    card_id: uuid.UUID | None = None
    account_id: uuid.UUID
    installment_number: int
    installment_total: int


class PreviewOut(BaseModel):
    items: list[PlannedRowOut]
    converted_total: MoneyObj | None = None  # set when the currency isn't the household's
