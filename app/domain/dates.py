"""Month arithmetic (specs/schemas.md §1, Conventions).

Rules:
- Adding N months keeps the day of month, clamped to the target month's length.
- A day-of-month setting (1-31) applied to a short month is clamped the same way.
- Series are always computed from their anchor, never from the previous item,
  so clamps never accumulate (day 31: Jan 31 -> Feb 28 -> Mar 31).
"""

import calendar
from datetime import date


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def shift_month(year: int, month: int, months: int) -> tuple[int, int]:
    """Return (year, month) moved by `months` (which may be negative)."""
    index = year * 12 + (month - 1) + months
    return index // 12, index % 12 + 1


def clamp_date(year: int, month: int, day: int) -> date:
    """Date for `day` in the given month, clamped to the month's last day."""
    if not 1 <= day <= 31:
        raise ValueError(f"day must be between 1 and 31, got {day}")
    return date(year, month, min(day, days_in_month(year, month)))


def add_months(anchor: date, months: int, day: int | None = None) -> date:
    """Move `anchor` by `months`, keeping `day` (default: the anchor's day), clamped."""
    year, month = shift_month(anchor.year, anchor.month, months)
    return clamp_date(year, month, anchor.day if day is None else day)


def monthly_series(anchor: date, count: int, day: int | None = None, interval: int = 1) -> list[date]:
    """`count` dates every `interval` months from `anchor`, all computed from the anchor."""
    if count < 1:
        raise ValueError("count must be at least 1")
    return [add_months(anchor, i * interval, day) for i in range(count)]


def first_of_month(d: date) -> date:
    return d.replace(day=1)


def month_index(d: date) -> int:
    """A monotonically increasing month number, handy for month comparisons."""
    return d.year * 12 + (d.month - 1)
