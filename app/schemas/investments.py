"""Investment bodies (specs/api.md §15)."""

import uuid
from datetime import date, datetime

from pydantic import BaseModel

from app.domain.enums import Currency, Liquidity
from app.schemas.common import MoneyIn, MoneyOut, OrmModel, Text


class InvestmentOut(OrmModel):
    id: uuid.UUID
    name: str | None
    bank: str
    amount: MoneyOut
    currency: Currency
    invested_on: date
    liquidity: Liquidity
    maturity_date: date | None
    include_in_balance: bool
    created_at: datetime
    updated_at: datetime


class InvestmentCreate(BaseModel):
    name: Text(40) | None = None
    bank: Text(40, min_length=1)
    amount: MoneyIn
    currency: Currency | None = None  # default: the household's currency
    invested_on: date | None = None  # default: today
    liquidity: Liquidity
    maturity_date: date | None = None  # required for MATURITY, rejected for DAILY
    include_in_balance: bool = True


class InvestmentPatch(BaseModel):
    """PATCH semantics: omitted fields are unchanged; null clears `name` and `maturity_date`."""

    name: Text(40) | None = None
    bank: Text(40, min_length=1) | None = None
    amount: MoneyIn | None = None
    currency: Currency | None = None
    invested_on: date | None = None
    liquidity: Liquidity | None = None
    maturity_date: date | None = None
    include_in_balance: bool | None = None
