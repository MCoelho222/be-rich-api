"""Payment dates and installment plans (specs/schemas.md §10.1, §10.2, §11.1)."""

from collections.abc import Container
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.business_days import next_business_day
from app.domain.credit import CardCycle, statement_for_purchase
from app.domain.dates import add_months, monthly_series
from app.domain.enums import EntryType, PaymentMethod
from app.domain.money import split_amount

MAX_INSTALLMENTS = 60


@dataclass(frozen=True)
class PlannedRow:
    installment_number: int
    installment_total: int
    amount: Decimal
    payment_date: date


def payment_dates(
    entry_type: EntryType,
    method: PaymentMethod,
    transaction_date: date,
    installments: int,
    holidays: Container[date],
    card_cycle: CardCycle | None = None,
) -> list[date]:
    """Payment date of each installment, in order.

    - Non-credit methods: the anchor is the transaction date; no adjustment.
    - Expense CREDIT: the anchor is the statement due date; each installment uses
      the card's due_day clamped to its own month, then the business-day shift.
    - Income CREDIT: the anchor is the same day next month; each installment is
      shifted to the next business day individually.
    """
    if not 1 <= installments <= MAX_INSTALLMENTS:
        raise ValueError(f"installments must be between 1 and {MAX_INSTALLMENTS}")
    if method is PaymentMethod.DEBIT and entry_type is EntryType.EXPENSE and installments != 1:
        raise ValueError("debit expenses cannot have installments")

    if method is not PaymentMethod.CREDIT:
        return monthly_series(transaction_date, installments)

    if entry_type is EntryType.EXPENSE:
        if card_cycle is None:
            raise ValueError("a credit expense needs the card's cycle")
        anchor = statement_for_purchase(transaction_date, card_cycle).nominal_due_date
        nominal = monthly_series(anchor, installments, day=card_cycle.due_day)
    else:
        anchor = add_months(transaction_date, 1)
        nominal = monthly_series(anchor, installments, day=transaction_date.day)
    return [next_business_day(d, holidays) for d in nominal]


def plan_rows(
    entry_type: EntryType,
    method: PaymentMethod,
    transaction_date: date,
    total: Decimal,
    installments: int,
    holidays: Container[date],
    card_cycle: CardCycle | None = None,
) -> list[PlannedRow]:
    """Amounts and payment dates of every row a single payment part creates."""
    dates = payment_dates(entry_type, method, transaction_date, installments, holidays, card_cycle)
    amounts = split_amount(total, installments)
    return [
        PlannedRow(i + 1, installments, amount, payment_date)
        for i, (amount, payment_date) in enumerate(zip(amounts, dates, strict=True))
    ]
