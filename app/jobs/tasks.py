"""The job functions. Each one flushes; the runner commits."""

from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import APP_TIMEZONE
from app.domain.enums import Currency, InvitationStatus
from app.domain.holidays import brazil_bank_holidays
from app.models import ExchangeRate, Holiday, Invitation, PasswordResetToken, RateLimitHit, Session as AuthSession
from app.services.fx import store_quotes
from app.services.fx_provider import RateProvider

HOLIDAY_YEARS_AHEAD = 2


def fx_daily(db: Session, now: datetime, provider: RateProvider) -> dict[str, int]:
    """Fetch the latest rates for every pair of supported currencies (§16.2).

    Scheduled hourly from 13:00 to 20:00; once a run has succeeded today the
    remaining runs do nothing. A provider error propagates, so the run is
    logged as failed and the next hourly run retries.
    """
    currencies = list(Currency)
    local_midnight = now.astimezone(APP_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    # Done today only if *every* pair was fetched today: on-demand historical
    # lookups also write rows, but only for single pairs.
    pairs_fetched_today = db.scalar(
        select(func.count(func.distinct(tuple_(ExchangeRate.base, ExchangeRate.quote)))).where(
            ExchangeRate.fetched_at >= local_midnight
        )
    )
    if pairs_fetched_today >= len(currencies) * (len(currencies) - 1):
        return {"skipped": 1, "stored": 0}
    stored = 0
    for base in currencies:
        quotes = provider.latest(base, [c for c in currencies if c != base])
        stored += store_quotes(db, quotes, provider.source, now)
    db.flush()
    return {"skipped": 0, "stored": stored}


def holidays_seed(db: Session, now: datetime) -> dict[str, int]:
    """Make sure `holiday` covers this year and the next two (§17.1). Never deletes."""
    year = now.astimezone(APP_TIMEZONE).year
    rows = [
        {"date": day, "name": name}
        for y in range(year, year + HOLIDAY_YEARS_AHEAD + 1)
        for day, name in brazil_bank_holidays(y).items()
    ]
    inserted = db.scalars(
        pg_insert(Holiday).values(rows).on_conflict_do_nothing(index_elements=["date"]).returning(Holiday.date)
    ).all()
    db.flush()
    return {"inserted": len(inserted)}


def invitations_expire(db: Session, now: datetime) -> dict[str, int]:
    """Mark PENDING invitations past their expiry as EXPIRED (schemas §6.1 rule 4)."""
    result = db.execute(
        update(Invitation)
        .where(Invitation.status == InvitationStatus.PENDING, Invitation.expires_at <= now)
        .values(status=InvitationStatus.EXPIRED)
    )
    db.flush()
    return {"expired": result.rowcount}


def sessions_cleanup(db: Session, now: datetime) -> dict[str, int]:
    """Delete invalid sessions, and reset tokens that are used or a day past expiry."""
    sessions = db.execute(
        delete(AuthSession).where(or_(AuthSession.expires_at <= now, AuthSession.absolute_expires_at <= now))
    )
    tokens = db.execute(
        delete(PasswordResetToken).where(
            or_(PasswordResetToken.used_at.is_not(None), PasswordResetToken.expires_at < now - timedelta(days=1))
        )
    )
    db.flush()
    return {"sessions": sessions.rowcount, "reset_tokens": tokens.rowcount}


def rate_limit_cleanup(db: Session, now: datetime) -> dict[str, int]:
    """Delete rate-limit hits older than the longest window (1 day)."""
    result = db.execute(delete(RateLimitHit).where(RateLimitHit.created_at < now - timedelta(days=1)))
    db.flush()
    return {"deleted": result.rowcount}
