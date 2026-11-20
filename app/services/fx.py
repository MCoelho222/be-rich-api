"""Exchange-rate lookups from the cached `exchange_rates` table (specs/schemas.md §16)."""

from datetime import date
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.domain.enums import Currency
from app.domain.fx import MissingRate, Rate, RateTable
from app.models import ExchangeRate


def rate_table(db: Session, base: Currency, quote: Currency, on_or_before: date | None = None) -> RateTable:
    """Rates for a pair (both directions), optionally limited to dates up to `on_or_before`."""
    stmt = select(ExchangeRate).where(
        or_(
            and_(ExchangeRate.base == base, ExchangeRate.quote == quote),
            and_(ExchangeRate.base == quote, ExchangeRate.quote == base),
        )
    )
    if on_or_before is not None:
        stmt = stmt.where(ExchangeRate.rate_date <= on_or_before)
    rows = db.scalars(stmt.order_by(ExchangeRate.rate_date.desc()).limit(10)).all()
    return RateTable(Rate(r.rate_date, r.base, r.quote, r.rate) for r in rows)


def latest_rate(db: Session, base: Currency, quote: Currency) -> tuple[Decimal, date | None] | None:
    """Latest base->quote rate and its date, or None when nothing is cached yet."""
    if base == quote:
        return Decimal(1), None
    try:
        return rate_table(db, base, quote).lookup(base, quote)
    except MissingRate:
        return None
