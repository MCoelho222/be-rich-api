"""Recurrence occurrences (specs/schemas.md §12.1 and §13.1)."""

from collections.abc import Callable, Container
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.domain.dates import add_months, month_index
from app.domain.enums import OccurrenceStatus

# Credit payment dates can land up to ~2 months after the occurrence; look back
# this far so occurrences paid inside a window are not missed.
PAYMENT_LOOKBACK = timedelta(days=70)


@dataclass(frozen=True)
class RecurrenceRule:
    start_date: date
    day_of_month: int
    interval_months: int = 1
    end_date: date | None = None
    is_active: bool = True
    skipped_dates: frozenset[date] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not 1 <= self.day_of_month <= 31:
            raise ValueError("day_of_month must be between 1 and 31")
        if not 1 <= self.interval_months <= 12:
            raise ValueError("interval_months must be between 1 and 12")
        if self.end_date is not None and self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")


def occurrence_dates(rule: RecurrenceRule, start: date, end: date) -> list[date]:
    """Occurrence dates within [start, end] and within the rule's own bounds.

    Dates are day `day_of_month` (clamped) of every `interval_months`-th month,
    counted from start_date's month and computed from that anchor. Skipping and
    pausing are not applied here: see `occurrence_status`.
    """
    last = end if rule.end_date is None else min(end, rule.end_date)
    first = max(start, rule.start_date)
    if first > last:
        return []
    anchor = rule.start_date.replace(day=1)
    # Jump straight to the first period that can be inside the window.
    k = max(0, (month_index(first) - month_index(anchor)) // rule.interval_months - 1)
    dates: list[date] = []
    while True:
        d = add_months(anchor, k * rule.interval_months, day=rule.day_of_month)
        if d > last:
            return dates
        if d >= first:
            dates.append(d)
        k += 1


def occurrence_status(
    occurrence: date, today: date, *, registered: bool, skipped: bool
) -> OccurrenceStatus:
    if registered:
        return OccurrenceStatus.REGISTERED
    if skipped:
        return OccurrenceStatus.SKIPPED
    if month_index(occurrence) == month_index(today):
        return OccurrenceStatus.PENDING
    if month_index(occurrence) < month_index(today):
        return OccurrenceStatus.OVERDUE
    return OccurrenceStatus.FUTURE


@dataclass(frozen=True)
class ProjectedOccurrence:
    occurrence_date: date
    payment_date: date
    status: OccurrenceStatus  # PENDING or FUTURE


def projected_occurrences(
    rule: RecurrenceRule,
    registered: Container[date],
    today: date,
    start: date,
    end: date,
    payment_date_of: Callable[[date], date],
) -> list[ProjectedOccurrence]:
    """Valid, unregistered, non-overdue occurrences paid within [start, end] (§13.1).

    `payment_date_of` maps an occurrence date to its payment date with the
    method's rules. A pending occurrence whose payment date has passed is
    placed on `today`. Overdue occurrences are excluded.
    """
    if not rule.is_active:
        return []
    window_start = max(start - PAYMENT_LOOKBACK, today.replace(day=1))
    result: list[ProjectedOccurrence] = []
    for occ in occurrence_dates(rule, window_start, end):
        status = occurrence_status(
            occ, today, registered=occ in registered, skipped=occ in rule.skipped_dates
        )
        if status not in (OccurrenceStatus.PENDING, OccurrenceStatus.FUTURE):
            continue
        paid = payment_date_of(occ)
        if status is OccurrenceStatus.PENDING and paid < today:
            paid = today
        if start <= paid <= end:
            result.append(ProjectedOccurrence(occ, paid, status))
    return result
