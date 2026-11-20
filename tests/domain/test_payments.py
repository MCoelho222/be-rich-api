from datetime import date
from decimal import Decimal

import pytest

from app.domain.credit import CardCycle, statement_for_purchase
from app.domain.enums import EntryType, PaymentMethod
from app.domain.holidays import brazil_bank_holidays
from app.domain.payments import payment_dates, plan_rows

HOLIDAYS = {d for y in (2026, 2027, 2028) for d in brazil_bank_holidays(y)}
EXPENSE, INCOME = EntryType.EXPENSE, EntryType.INCOME
CREDIT = PaymentMethod.CREDIT


# The example table from specs/schemas.md §10.3
@pytest.mark.parametrize(
    "best,due,purchase,closing,payment",
    [
        (25, 5, date(2026, 11, 10), date(2026, 11, 25), date(2026, 12, 7)),  # Dec 5 is Saturday
        (25, 5, date(2026, 11, 25), date(2026, 12, 25), date(2027, 1, 5)),
        (25, 5, date(2026, 12, 2), date(2026, 12, 25), date(2027, 1, 5)),
        (3, 10, date(2026, 11, 1), date(2026, 11, 3), date(2026, 11, 10)),
        (3, 10, date(2026, 11, 5), date(2026, 12, 3), date(2026, 12, 10)),
    ],
)
def test_spec_credit_examples(best, due, purchase, closing, payment):
    cycle = CardCycle(best, due)
    assert statement_for_purchase(purchase, cycle).closing_date == closing
    assert payment_dates(EXPENSE, CREDIT, purchase, 1, HOLIDAYS, cycle) == [payment]


def test_best_buy_day_clamped_in_short_month():
    # B=31 in February is the 28th: a purchase on Feb 28 already goes to the next statement.
    cycle = CardCycle(31, 10)
    assert statement_for_purchase(date(2026, 2, 27), cycle).closing_date == date(2026, 2, 28)
    assert statement_for_purchase(date(2026, 2, 28), cycle).closing_date == date(2026, 3, 31)


def test_credit_installments_use_due_day_per_month_then_adjust():
    cycle = CardCycle(25, 31)  # D > B: due in the closing month
    dates = payment_dates(EXPENSE, CREDIT, date(2026, 1, 10), 3, HOLIDAYS, cycle)
    # Nominal: Jan 31 (Sat), Feb 28 (Sat), Mar 31 (Tue) -> no clamp accumulation
    assert dates == [date(2026, 2, 2), date(2026, 3, 2), date(2026, 3, 31)]


def test_non_credit_installments_are_monthly_without_adjustment():
    dates = payment_dates(EXPENSE, PaymentMethod.BOLETO, date(2026, 1, 31), 3, HOLIDAYS)
    assert dates == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]  # Jan 31 is Saturday: kept


def test_income_credit_is_same_day_next_month_adjusted():
    # 2026-12-20 is a Sunday -> Monday 21 (ui-behavior §7 example)
    assert payment_dates(INCOME, CREDIT, date(2026, 11, 20), 1, HOLIDAYS) == [date(2026, 12, 21)]


def test_debit_expense_cannot_have_installments():
    with pytest.raises(ValueError):
        payment_dates(EXPENSE, PaymentMethod.DEBIT, date(2026, 11, 20), 2, HOLIDAYS)


def test_credit_expense_requires_cycle():
    with pytest.raises(ValueError):
        payment_dates(EXPENSE, CREDIT, date(2026, 11, 20), 1, HOLIDAYS)


def test_plan_rows_combines_amounts_and_dates():
    rows = plan_rows(EXPENSE, CREDIT, date(2026, 11, 10), Decimal("100.00"), 3, HOLIDAYS, CardCycle(25, 5))
    assert [(r.installment_number, r.amount, r.payment_date) for r in rows] == [
        (1, Decimal("33.34"), date(2026, 12, 7)),
        (2, Decimal("33.33"), date(2027, 1, 5)),
        (3, Decimal("33.33"), date(2027, 2, 5)),
    ]
    assert all(r.installment_total == 3 for r in rows)
