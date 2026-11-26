"""Read-model responses (specs/api.md §13)."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer

from app.domain.enums import Currency, EntryType, OccurrenceStatus, PaymentMethod
from app.schemas.common import MoneyOut
from app.schemas.entries import ExpenseOut, IncomeOut

Share = Annotated[Decimal, PlainSerializer(lambda v: f"{v:.4f}", return_type=str)]


class MoneyAmount(BaseModel):
    currency: Currency
    amount: MoneyOut


class Converted(BaseModel):
    """The conversion block every read model carries (§13.1)."""

    currency: Currency
    rates_as_of: date | None
    unconverted: list[MoneyAmount]


class AccountBalanceOut(BaseModel):
    account_id: uuid.UUID
    account_currency: Currency
    balance: MoneyOut | None
    converted: MoneyOut | None


class BalancesOut(Converted):
    date: date
    projected: bool
    total: MoneyOut
    accounts: list[AccountBalanceOut]
    investments: MoneyOut  # included in `total` (schemas §20.1); 0 with an account filter


class RealizedTotal(BaseModel):
    realized: MoneyOut
    total: MoneyOut


class FixedExpenses(BaseModel):
    total: MoneyOut
    share: Share | None


class SummaryOut(Converted):
    from_: date = Field(alias="from")
    to: date
    includes_projection: bool
    income: RealizedTotal
    expenses: RealizedTotal
    net: RealizedTotal
    fixed_expenses: FixedExpenses


class MonthPart(BaseModel):
    realized: MoneyOut
    scheduled: MoneyOut
    projected_fixed: MoneyOut
    total: MoneyOut


class MonthOut(BaseModel):
    month: str
    income: MonthPart
    expenses: MonthPart
    net: MoneyOut
    end_balance: MoneyOut | None
    end_balance_projected: bool
    end_investments: MoneyOut  # included in `end_balance` (schemas §20.1)


class ProjectionOut(Converted):
    from_: date = Field(alias="from")
    to: date
    months: list[MonthOut]
    first_negative_month: str | None


class CategoryTotal(BaseModel):
    category_id: uuid.UUID
    realized: MoneyOut
    total: MoneyOut
    share: Share | None


class CategoriesOut(Converted):
    type: EntryType
    from_: date = Field(alias="from")
    to: date
    total: MoneyOut
    items: list[CategoryTotal]


class CardBillOut(BaseModel):
    card_id: uuid.UUID
    due_date: date
    closes_on: date
    rows_total: MoneyOut
    projected_fixed: MoneyOut
    total: MoneyOut
    rows_count: int


class CardBillsOut(Converted):
    items: list[CardBillOut]


class ProjectedOccurrenceOut(BaseModel):
    recurrence_id: uuid.UUID
    occurrence_date: date
    status: OccurrenceStatus
    description: str | None
    category_id: uuid.UUID
    account_id: uuid.UUID
    card_id: uuid.UUID | None
    person_id: uuid.UUID
    payment_method: PaymentMethod


class ProjectionItemOut(BaseModel):
    type: EntryType
    projected: bool
    payment_date: date
    amount: MoneyOut
    currency: Currency
    converted: MoneyOut | None
    row: ExpenseOut | IncomeOut | None
    occurrence: ProjectedOccurrenceOut | None


class ProjectionItemsOut(Converted):
    items: list[ProjectionItemOut]
    next_cursor: str | None
