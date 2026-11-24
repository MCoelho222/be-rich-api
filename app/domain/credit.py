"""Credit card statement algorithm (specs/schemas.md §10.3)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from app.domain.dates import clamp_date, shift_month


@dataclass(frozen=True)
class CardCycle:
    best_buy_day: int  # B: first day of a new statement cycle
    due_day: int  # D: nominal day the statement is due

    def __post_init__(self) -> None:
        for name in ("best_buy_day", "due_day"):
            value = getattr(self, name)
            if not 1 <= value <= 31:
                raise ValueError(f"{name} must be between 1 and 31, got {value}")


@dataclass(frozen=True)
class Statement:
    closing_date: date
    nominal_due_date: date  # before any business-day adjustment


def statement_for_purchase(purchase: date, cycle: CardCycle) -> Statement:
    """Find the statement a purchase belongs to and its nominal due date.

    1. If purchase.day < B (clamped to the purchase month), the statement closes
       in the purchase month; otherwise (including on B itself) the next month.
    2. If D > B, the statement is due on day D of the closing month; otherwise
       on day D of the month after the closing month.
    """
    best_in_purchase_month = clamp_date(purchase.year, purchase.month, cycle.best_buy_day)
    if purchase < best_in_purchase_month:
        closing_year, closing_month = purchase.year, purchase.month
    else:
        closing_year, closing_month = shift_month(purchase.year, purchase.month, 1)
    return statement_closing_in(closing_year, closing_month, cycle)


def statement_closing_in(year: int, month: int, cycle: CardCycle) -> Statement:
    """The statement that closes in the given month."""
    closing_date = clamp_date(year, month, cycle.best_buy_day)
    if cycle.due_day > cycle.best_buy_day:
        due_year, due_month = year, month
    else:
        due_year, due_month = shift_month(year, month, 1)
    return Statement(closing_date, clamp_date(due_year, due_month, cycle.due_day))


def statement_due_in(year: int, month: int, cycle: CardCycle) -> Statement:
    """The statement whose nominal due date falls in the given month."""
    if cycle.due_day > cycle.best_buy_day:
        return statement_closing_in(year, month, cycle)
    return statement_closing_in(*shift_month(year, month, -1), cycle)


def purchase_window(statement: Statement, cycle: CardCycle) -> tuple[date, date]:
    """The first and last purchase dates that belong to `statement`."""
    closing = statement.closing_date
    year, month = shift_month(closing.year, closing.month, -1)
    return clamp_date(year, month, cycle.best_buy_day), closing - timedelta(days=1)


def next_statement(
    today: date, cycle: CardCycle, shift: Callable[[date], date]
) -> tuple[Statement, date]:
    """The first statement whose due date, after `shift` (the business-day rule), is
    today or later. Returns it with its shifted due date (api.md §13.6)."""
    for k in range(-2, 3):
        year, month = shift_month(today.year, today.month, k)
        statement = statement_closing_in(year, month, cycle)
        due = shift(statement.nominal_due_date)
        if due >= today:
            return statement, due
    raise AssertionError("a statement is always due within two months")  # pragma: no cover
