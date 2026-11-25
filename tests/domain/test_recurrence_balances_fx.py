from datetime import date
from decimal import Decimal

import pytest

from app.domain.balances import Movement, account_balance
from app.domain.enums import Currency, EntryType, OccurrenceStatus
from app.domain.fx import MissingRate, Rate, RateTable, rate_date_for
from app.domain.recurrence import (
    RecurrenceRule,
    occurrence_dates,
    occurrence_status,
    projected_occurrences,
)

TODAY = date(2026, 11, 20)


class TestOccurrences:
    def test_monthly_day_31_does_not_accumulate_clamps(self):
        rule = RecurrenceRule(start_date=date(2026, 1, 31), day_of_month=31)
        assert occurrence_dates(rule, date(2026, 1, 1), date(2026, 3, 31)) == [
            date(2026, 1, 31),
            date(2026, 2, 28),
            date(2026, 3, 31),
        ]

    def test_dates_before_start_date_are_dropped(self):
        rule = RecurrenceRule(start_date=date(2026, 1, 20), day_of_month=5)
        assert occurrence_dates(rule, date(2026, 1, 1), date(2026, 3, 31)) == [
            date(2026, 2, 5),
            date(2026, 3, 5),
        ]

    def test_yearly_and_end_date(self):
        rule = RecurrenceRule(
            start_date=date(2026, 3, 10), day_of_month=10, interval_months=12, end_date=date(2028, 3, 9)
        )
        assert occurrence_dates(rule, date(2020, 1, 1), date(2030, 1, 1)) == [
            date(2026, 3, 10),
            date(2027, 3, 10),
        ]

    def test_window_far_after_start(self):
        rule = RecurrenceRule(start_date=date(2020, 1, 5), day_of_month=5, interval_months=3)
        assert occurrence_dates(rule, date(2026, 11, 1), date(2027, 3, 31)) == [
            date(2027, 1, 5),
        ]

    @pytest.mark.parametrize(
        "occ,registered,skipped,expected",
        [
            (date(2026, 11, 5), True, False, OccurrenceStatus.REGISTERED),
            (date(2026, 11, 5), False, True, OccurrenceStatus.SKIPPED),
            (date(2026, 11, 5), False, False, OccurrenceStatus.PENDING),
            (date(2026, 11, 30), False, False, OccurrenceStatus.PENDING),
            (date(2026, 10, 31), False, False, OccurrenceStatus.OVERDUE),
            (date(2026, 12, 1), False, False, OccurrenceStatus.FUTURE),
        ],
    )
    def test_status(self, occ, registered, skipped, expected):
        assert occurrence_status(occ, TODAY, registered=registered, skipped=skipped) == expected


class TestProjection:
    rule = RecurrenceRule(
        start_date=date(2026, 9, 5), day_of_month=5, skipped_dates=frozenset({date(2027, 1, 5)})
    )

    def project(self, rule=None, registered=(), start=date(2026, 11, 1), end=date(2027, 2, 28)):
        return projected_occurrences(
            rule or self.rule, set(registered), TODAY, start, end, payment_date_of=lambda d: d
        )

    def test_excludes_overdue_skipped_and_registered(self):
        result = self.project(registered={date(2026, 12, 5)})
        # Sep/Oct are overdue, Dec registered, Jan skipped
        assert [p.occurrence_date for p in result] == [date(2026, 11, 5), date(2027, 2, 5)]

    def test_pending_with_past_payment_date_is_placed_today(self):
        first = self.project()[0]
        assert first.status is OccurrenceStatus.PENDING
        assert first.payment_date == TODAY

    def test_paused_recurrence_projects_nothing(self):
        paused = RecurrenceRule(start_date=date(2026, 9, 5), day_of_month=5, is_active=False)
        assert self.project(rule=paused) == []

    def test_occurrence_paid_inside_window_is_found_via_lookback(self):
        # Credit-like: occurrence in December, paid in January
        result = projected_occurrences(
            RecurrenceRule(start_date=date(2026, 12, 28), day_of_month=28),
            set(),
            TODAY,
            date(2027, 1, 1),
            date(2027, 1, 31),
            payment_date_of=lambda d: date(d.year + (d.month == 12), d.month % 12 + 1, 5),
        )
        assert [(p.occurrence_date, p.payment_date) for p in result] == [
            (date(2026, 12, 28), date(2027, 1, 5))
        ]


class TestBalances:
    opening_date = date(2026, 11, 1)
    movements = [
        Movement(EntryType.INCOME, date(2026, 11, 1), Decimal("999.00")),  # part of the opening
        Movement(EntryType.INCOME, date(2026, 11, 5), Decimal("5000.00")),
        Movement(EntryType.EXPENSE, date(2026, 11, 10), Decimal("1200.50")),
        Movement(EntryType.EXPENSE, date(2026, 12, 7), Decimal("100.00")),
    ]

    def test_rows_on_or_before_opening_date_are_ignored(self):
        assert account_balance(Decimal("1000.00"), self.opening_date, self.movements, self.opening_date) == Decimal("1000.00")

    def test_balance_on_date(self):
        assert account_balance(Decimal("1000.00"), self.opening_date, self.movements, TODAY) == Decimal("4799.50")
        assert account_balance(Decimal("1000.00"), self.opening_date, self.movements, date(2026, 12, 31)) == Decimal("4699.50")

    def test_before_opening_is_undefined(self):
        assert account_balance(Decimal("0"), self.opening_date, [], date(2026, 10, 31)) is None

    def test_negative_balance_allowed(self):
        assert account_balance(Decimal("-50.00"), self.opening_date, [], TODAY) == Decimal("-50.00")


class TestRates:
    table = RateTable(
        [
            Rate(date(2026, 11, 18), Currency.USD, Currency.BRL, Decimal("5.40")),
            Rate(date(2026, 11, 20), Currency.USD, Currency.BRL, Decimal("5.45")),
            Rate(date(2026, 11, 19), Currency.BRL, Currency.EUR, Decimal("0.16")),
        ]
    )

    def test_exact_and_previous_day_fallback(self):
        assert self.table.lookup(Currency.USD, Currency.BRL, date(2026, 11, 18)) == (Decimal("5.40"), date(2026, 11, 18))
        # Saturday-like gap: 19th has no USD rate -> use the 18th
        assert self.table.lookup(Currency.USD, Currency.BRL, date(2026, 11, 19)) == (Decimal("5.40"), date(2026, 11, 18))

    def test_latest(self):
        assert self.table.lookup(Currency.USD, Currency.BRL) == (Decimal("5.45"), date(2026, 11, 20))

    def test_inverse_pair(self):
        rate, on = self.table.lookup(Currency.EUR, Currency.BRL)
        assert on == date(2026, 11, 19)
        assert rate == 1 / Decimal("0.16")

    def test_same_currency(self):
        assert self.table.lookup(Currency.BRL, Currency.BRL)[0] == Decimal(1)

    def test_missing(self):
        with pytest.raises(MissingRate):
            self.table.lookup(Currency.USD, Currency.BRL, date(2026, 1, 1))
        with pytest.raises(MissingRate):
            self.table.lookup(Currency.USD, Currency.EUR)

    def test_rate_date_rule(self):
        assert rate_date_for(date(2026, 11, 10), TODAY) == date(2026, 11, 10)
        assert rate_date_for(date(2026, 12, 7), TODAY) is None
