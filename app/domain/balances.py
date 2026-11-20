"""Account balances (specs/schemas.md §14.1)."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.enums import EntryType


@dataclass(frozen=True)
class Movement:
    """A row's effect on its account, already in the account's currency."""

    entry_type: EntryType
    payment_date: date
    amount: Decimal  # positive; the entry type gives the direction

    @property
    def signed(self) -> Decimal:
        return self.amount if self.entry_type is EntryType.INCOME else -self.amount


def account_balance(
    opening_balance: Decimal,
    opening_balance_date: date,
    movements: Iterable[Movement],
    at: date,
) -> Decimal | None:
    """End-of-day balance on `at`.

    Rows paid on or before `opening_balance_date` are already part of the opening
    balance and are ignored. Returns None for dates before the opening date.
    """
    if at < opening_balance_date:
        return None
    return opening_balance + sum(
        (m.signed for m in movements if opening_balance_date < m.payment_date <= at),
        Decimal("0"),
    )
