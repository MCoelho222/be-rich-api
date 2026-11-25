"""Business-day adjustment (specs/schemas.md §17).

A business day is Monday-Friday and not a bank holiday. Adjusted dates move
forward to the next business day. The holiday set is supplied by the caller
(from the `holiday` table, or `brazil_bank_holidays` in tests).
"""

from collections.abc import Container
from datetime import date, timedelta

SATURDAY = 5


def is_business_day(d: date, holidays: Container[date]) -> bool:
    return d.weekday() < SATURDAY and d not in holidays


def next_business_day(d: date, holidays: Container[date]) -> date:
    """`d` itself if it is a business day, otherwise the next one."""
    while not is_business_day(d, holidays):
        d += timedelta(days=1)
    return d
