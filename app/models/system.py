"""System-wide tables, not owned by a household (specs/schemas.md §16.1, §17.1)."""

import datetime as dt
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, RateValue, UUIDPk, str_enum
from app.domain.enums import Currency


class ExchangeRate(UUIDPk, Base):
    __tablename__ = "exchange_rates"
    __table_args__ = (
        UniqueConstraint("rate_date", "base", "quote", name="uq_exchange_rates_date_pair"),
        CheckConstraint("rate > 0", name="rate_positive"),
        CheckConstraint("base <> quote", name="distinct_pair"),
    )

    rate_date: Mapped[date] = mapped_column(Date)
    base: Mapped[Currency] = mapped_column(str_enum(Currency, "base_currency"))
    quote: Mapped[Currency] = mapped_column(str_enum(Currency, "quote_currency"))
    rate: Mapped[Decimal] = mapped_column(RateValue)
    source: Mapped[str] = mapped_column(String(40))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Holiday(Base):
    __tablename__ = "holidays"

    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
