"""Next card statement (specs/api.md §13.6)."""

from datetime import date

import pytest

from app.domain.business_days import next_business_day
from app.domain.credit import CardCycle, next_statement, statement_closing_in, statement_for_purchase
from app.domain.holidays import brazil_bank_holidays

HOLIDAYS = set(brazil_bank_holidays(2026)) | set(brazil_bank_holidays(2027))


def shift(d: date) -> date:
    return next_business_day(d, HOLIDAYS)


@pytest.mark.parametrize(
    "today,b,d,closing,due",
    [
        # D < B: due the month after closing. Dec 5 2026 is a Saturday -> Monday.
        (date(2026, 11, 20), 25, 5, date(2026, 11, 25), date(2026, 12, 7)),
        # The previous bill is still ahead: closed Nov 1, due Nov 10.
        (date(2026, 11, 5), 1, 10, date(2026, 11, 1), date(2026, 11, 10)),
        # Due today counts as the next bill.
        (date(2026, 11, 10), 1, 10, date(2026, 11, 1), date(2026, 11, 10)),
        (date(2026, 11, 11), 1, 10, date(2026, 12, 1), date(2026, 12, 10)),
        # Day 31 clamps in short months.
        (date(2027, 2, 11), 31, 10, date(2027, 2, 28), date(2027, 3, 10)),
    ],
)
def test_next_statement(today, b, d, closing, due):
    statement, shifted = next_statement(today, CardCycle(b, d), shift)
    assert (statement.closing_date, shifted) == (closing, due)


def test_closing_in_matches_purchase_rule():
    cycle = CardCycle(25, 5)
    for purchase in (date(2026, 11, 1), date(2026, 11, 24), date(2026, 11, 25), date(2026, 12, 31)):
        found = statement_for_purchase(purchase, cycle)
        assert found == statement_closing_in(found.closing_date.year, found.closing_date.month, cycle)
