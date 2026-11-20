"""Recurrences and occurrences (specs/api.md §12)."""

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.domain.enums import Currency, EntryType, OccurrenceStatus, PaymentMethod
from app.schemas.common import MoneyIn, MoneyOut, OrmModel, Text
from app.schemas.entries import ExpenseOut, IncomeOut

Day = Annotated[int, Field(ge=1, le=31)]
Interval = Annotated[int, Field(ge=1, le=12)]
RecurrenceStatus = Literal["ACTIVE", "PAUSED", "ENDED"]


class RegisterFirst(BaseModel):
    occurrence_date: dt.date
    amount: MoneyIn | None = None
    description: Text(200) | None = None


class RecurrenceCreate(BaseModel):
    type: EntryType
    person_id: uuid.UUID | None = None  # default: the caller
    amount: MoneyIn
    currency: Currency | None = None
    payment_method: PaymentMethod
    card_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    category_id: uuid.UUID
    description: Text(200) | None = None
    interval_months: Interval = 1
    day_of_month: Day | None = None  # default: start_date's day
    start_date: dt.date | None = None  # default: today
    end_date: dt.date | None = None
    register_first: RegisterFirst | None = None


class RecurrencePatch(BaseModel):
    person_id: uuid.UUID | None = None
    amount: MoneyIn | None = None
    currency: Currency | None = None
    payment_method: PaymentMethod | None = None
    card_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    description: Text(200) | None = None
    interval_months: Interval | None = None
    day_of_month: Day | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None


class EndIn(BaseModel):
    end_date: dt.date | None = None  # default: today


class ChangeAmountIn(BaseModel):
    effective_date: dt.date
    amount: MoneyIn


class RegisterIn(BaseModel):
    amount: MoneyIn | None = None
    transaction_date: dt.date | None = None  # default: the occurrence date
    description: Text(200) | None = None
    account_id: uuid.UUID | None = None
    card_id: uuid.UUID | None = None
    person_id: uuid.UUID | None = None


class OccurrenceOut(BaseModel):
    occurrence_date: dt.date
    payment_date: dt.date
    expected_amount: MoneyOut
    currency: Currency
    status: OccurrenceStatus
    row_id: uuid.UUID | None


class OverdueOut(OccurrenceOut):
    recurrence_id: uuid.UUID


class NextOccurrence(BaseModel):
    occurrence_date: dt.date
    payment_date: dt.date
    status: OccurrenceStatus


class RecurrenceOut(OrmModel):
    id: uuid.UUID
    type: EntryType
    person_id: uuid.UUID
    amount: MoneyOut
    currency: Currency
    payment_method: PaymentMethod
    card_id: uuid.UUID | None
    account_id: uuid.UUID
    category_id: uuid.UUID
    description: str | None
    interval_months: int
    day_of_month: int
    start_date: dt.date
    end_date: dt.date | None
    skipped_dates: list[dt.date]
    is_active: bool
    status: RecurrenceStatus
    next_occurrence: NextOccurrence | None
    created_by_id: uuid.UUID
    created_at: dt.datetime
    updated_at: dt.datetime


class RecurrenceCreated(BaseModel):
    recurrence: RecurrenceOut
    registered: ExpenseOut | IncomeOut | None


class AmountChanged(BaseModel):
    ended: RecurrenceOut
    created: RecurrenceOut
