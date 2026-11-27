"""Transfer bodies (specs/api.md §16)."""

import uuid
import datetime as dt

from pydantic import BaseModel

from app.domain.enums import Currency, TransferEnd
from app.schemas.common import MoneyIn, MoneyOut, OrmModel, Text


class TransferEndIn(BaseModel):
    kind: TransferEnd
    id: uuid.UUID


class TransferCreate(BaseModel):
    source: TransferEndIn
    target: TransferEndIn
    amount: MoneyIn  # in the source's currency
    # Required when the two ends use different currencies; ignored when they match.
    amount_received: MoneyIn | None = None
    date: dt.date | None = None  # default: today; never in the future
    description: Text(200) | None = None


class TransferEndOut(BaseModel):
    kind: TransferEnd
    account_id: uuid.UUID | None
    investment_id: uuid.UUID | None  # null once the investment was deleted
    label: str | None  # the investment's name or bank when the transfer was made


class TransferOut(OrmModel):
    id: uuid.UUID
    date: dt.date
    description: str | None
    source: TransferEndOut
    target: TransferEndOut
    amount_sent: MoneyOut
    currency_sent: Currency
    amount_received: MoneyOut
    currency_received: Currency
    created_at: dt.datetime
