from datetime import date
from decimal import Decimal

import pytest

from app.domain.dates import add_months, clamp_date, monthly_series, shift_month
from app.domain.money import round_money, split_amount, to_money


class TestMonthArithmetic:
    def test_add_month_clamps_to_month_end(self):
        assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)

    def test_leap_year(self):
        assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)

    def test_negative_and_year_rollover(self):
        assert add_months(date(2026, 1, 15), -1) == date(2025, 12, 15)
        assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
        assert shift_month(2026, 12, 1) == (2027, 1)

    def test_series_computed_from_anchor_never_accumulates_clamps(self):
        assert monthly_series(date(2026, 1, 31), 3) == [
            date(2026, 1, 31),
            date(2026, 2, 28),
            date(2026, 3, 31),
        ]

    def test_series_with_explicit_day_and_interval(self):
        assert monthly_series(date(2026, 2, 28), 3, day=31, interval=12) == [
            date(2026, 2, 28),
            date(2027, 2, 28),
            date(2028, 2, 29),
        ]

    def test_clamp_rejects_invalid_day(self):
        with pytest.raises(ValueError):
            clamp_date(2026, 1, 0)


class TestMoney:
    def test_spec_example_100_in_3(self):
        assert split_amount(Decimal("100.00"), 3) == [
            Decimal("33.34"),
            Decimal("33.33"),
            Decimal("33.33"),
        ]

    @pytest.mark.parametrize("total,parts", [("0.03", 3), ("1000.01", 7), ("59.99", 60), ("10", 1)])
    def test_parts_always_sum_to_total(self, total, parts):
        amounts = split_amount(Decimal(total), parts)
        assert sum(amounts) == Decimal(total)
        assert len(amounts) == parts
        assert all(a > 0 for a in amounts)

    def test_total_too_small_to_split(self):
        with pytest.raises(ValueError):
            split_amount(Decimal("0.02"), 3)

    def test_floats_and_extra_decimals_rejected(self):
        with pytest.raises(TypeError):
            to_money(1.5)  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            to_money("1.005")
        assert to_money("12") == Decimal("12.00")

    def test_round_money_is_bankers(self):
        assert round_money(Decimal("0.125")) == Decimal("0.12")
        assert round_money(Decimal("0.135")) == Decimal("0.14")
