"""Exchange-rate lookups from the cached `exchange_rates` table (specs/schemas.md §16)."""

import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.domain.enums import Currency
from app.domain.fx import MissingRate, Rate, RateTable
from app.models import ExchangeRate
from app.services.fx_provider import Quote, RateProvider, RateProviderError

logger = logging.getLogger(__name__)


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


def store_quotes(db: Session, quotes: list[Quote], source: str, now: datetime) -> int:
    """Upsert provider quotes into the cache. Returns how many rows were written."""
    if not quotes:
        return 0
    stmt = pg_insert(ExchangeRate).values(
        [
            {"id": uuid.uuid4(), "rate_date": q.rate_date, "base": q.base, "quote": q.quote, "rate": q.rate,
             "source": source, "fetched_at": now}  # fmt: skip
            for q in quotes
            if q.base != q.quote
        ]
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_exchange_rates_date_pair",
        set_={"rate": stmt.excluded.rate, "source": stmt.excluded.source, "fetched_at": stmt.excluded.fetched_at},
    )
    db.execute(stmt)
    return len(quotes)


HISTORICAL_GAP = timedelta(days=6)  # weekends and holidays have no rates


def historical_rate(
    db: Session, provider: RateProvider, base: Currency, quote: Currency, day: date, now: datetime
) -> tuple[Decimal, date | None] | None:
    """The rate for a past `day` (specs/operations.md §2.3).

    Uses the cache when it has a rate within a few days before `day`; otherwise
    fetches that date from the provider and caches it. If the provider fails,
    falls back to the most recent cached rate on or before `day` (§16.4).
    """
    if base == quote:
        return Decimal(1), None
    try:
        rate, rate_date = rate_table(db, base, quote, on_or_before=day).lookup(base, quote, day)
        if rate_date is not None and day - rate_date <= HISTORICAL_GAP:
            return rate, rate_date
    except MissingRate:
        pass
    try:
        store_quotes(db, provider.on(day, base, [quote]), provider.source, now)
        db.flush()
    except RateProviderError:
        logger.warning("Historical rate %s->%s on %s unavailable; using the cache", base, quote, day)
    try:
        return rate_table(db, base, quote, on_or_before=day).lookup(base, quote, day)
    except MissingRate:
        return None


def latest_rate(db: Session, base: Currency, quote: Currency) -> tuple[Decimal, date | None] | None:
    """Latest base->quote rate and its date, or None when nothing is cached yet."""
    if base == quote:
        return Decimal(1), None
    try:
        return rate_table(db, base, quote).lookup(base, quote)
    except MissingRate:
        return None
