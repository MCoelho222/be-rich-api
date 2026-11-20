"""Currency conversion (specs/schemas.md §15 and §16.3)."""

import bisect
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.enums import Currency


@dataclass(frozen=True)
class Rate:
    rate_date: date
    base: Currency
    quote: Currency
    rate: Decimal  # 1 base = rate * quote


class MissingRate(LookupError):
    pass


class RateTable:
    """In-memory view of cached rates with the spec's lookup rules.

    - A date lookup uses that day's rate or the most recent earlier one
      (weekends and holidays have no rates).
    - A pair missing in one direction is served by the inverse of the other.
    """

    def __init__(self, rates: Iterable[Rate]) -> None:
        self._dates: dict[tuple[Currency, Currency], list[date]] = defaultdict(list)
        self._values: dict[tuple[Currency, Currency, date], Decimal] = {}
        for r in rates:
            key = (r.base, r.quote)
            if (r.base, r.quote, r.rate_date) not in self._values:
                bisect.insort(self._dates[key], r.rate_date)
            self._values[(r.base, r.quote, r.rate_date)] = r.rate

    def _direct(self, base: Currency, quote: Currency, on: date | None) -> tuple[Decimal, date] | None:
        dates = self._dates.get((base, quote))
        if not dates:
            return None
        idx = len(dates) - 1 if on is None else bisect.bisect_right(dates, on) - 1
        if idx < 0:
            return None
        found = dates[idx]
        return self._values[(base, quote, found)], found

    def lookup(self, base: Currency, quote: Currency, on: date | None = None) -> tuple[Decimal, date | None]:
        """Rate for base->quote on `on` (None = latest) and the date it refers to."""
        if base == quote:
            return Decimal(1), on
        direct = self._direct(base, quote, on)
        inverse = self._direct(quote, base, on)
        candidates = [c for c in (direct, inverse and (1 / inverse[0], inverse[1])) if c]
        if not candidates:
            raise MissingRate(f"no {base}->{quote} rate" + (f" on or before {on}" if on else ""))
        return max(candidates, key=lambda c: c[1])  # prefer the most recent


def rate_date_for(payment_date: date, today: date) -> date | None:
    """Which rate a row uses (§16.3): historical for past rows, latest (None) otherwise."""
    return payment_date if payment_date <= today else None


def convert(amount: Decimal, rate: Decimal) -> Decimal:
    """Full-precision conversion. Round only the final aggregate (§15)."""
    return amount * rate
