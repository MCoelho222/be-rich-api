"""The single place that reads the clock.

"Today" is always the calendar date in America/Sao_Paulo (specs/schemas.md §1).
Domain code never calls this: services pass `today` into the domain functions.
"""

from datetime import date, datetime, timezone

from app.core.config import APP_TIMEZONE


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today() -> date:
    return datetime.now(APP_TIMEZONE).date()
