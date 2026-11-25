from datetime import date

import pytest

from app.domain.business_days import is_business_day, next_business_day
from app.domain.holidays import brazil_bank_holidays, easter_sunday


@pytest.mark.parametrize(
    "year,expected",
    [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28))],
)
def test_easter(year, expected):
    assert easter_sunday(year) == expected


def test_2026_movable_bank_holidays():
    h = brazil_bank_holidays(2026)
    assert h[date(2026, 2, 16)].startswith("Carnaval")
    assert h[date(2026, 2, 17)].startswith("Carnaval")
    assert h[date(2026, 4, 3)] == "Sexta-feira Santa"
    assert h[date(2026, 6, 4)] == "Corpus Christi"


def test_consciencia_negra_only_from_2024():
    assert date(2026, 11, 20) in brazil_bank_holidays(2026)
    assert date(2023, 11, 20) not in brazil_bank_holidays(2023)


class TestBusinessDays:
    holidays = brazil_bank_holidays(2026)

    def test_weekday_is_business_day(self):
        assert is_business_day(date(2026, 11, 19), self.holidays)  # Thursday

    def test_saturday_moves_to_monday(self):
        assert next_business_day(date(2026, 12, 5), self.holidays) == date(2026, 12, 7)

    def test_holiday_moves_forward(self):
        # Fri 2026-11-20 is a holiday -> Monday 23
        assert next_business_day(date(2026, 11, 20), self.holidays) == date(2026, 11, 23)

    def test_carnival_moves_to_wednesday(self):
        assert next_business_day(date(2026, 2, 16), self.holidays) == date(2026, 2, 18)
