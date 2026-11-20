"""Holiday lookup for business-day adjustments (specs/schemas.md §17)."""

from datetime import date

from sqlalchemy import extract, select
from sqlalchemy.orm import Session

from app.domain.holidays import brazil_bank_holidays
from app.models import Holiday


def load_holidays(db: Session, first_year: int, last_year: int) -> set[date]:
    """Bank holidays for the given years, from the `holiday` table.

    Years the seed job hasn't covered yet fall back to the computed national
    calendar, so date rules never silently ignore holidays.
    """
    rows = db.scalars(
        select(Holiday.date).where(extract("year", Holiday.date).between(first_year, last_year))
    ).all()
    holidays = set(rows)
    covered = {d.year for d in holidays}
    for year in range(first_year, last_year + 1):
        if year not in covered:
            holidays |= set(brazil_bank_holidays(year))
    return holidays


def holidays_around(db: Session, *dates: date, years_after: int = 1) -> set[date]:
    """Holidays from the earliest given date's year to `years_after` past the latest."""
    return load_holidays(db, min(d.year for d in dates), max(d.year for d in dates) + years_after)
