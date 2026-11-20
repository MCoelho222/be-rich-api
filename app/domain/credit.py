"""Credit card statement algorithm (specs/schemas.md §10.3)."""

from dataclasses import dataclass
from datetime import date

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
    closing_date = clamp_date(closing_year, closing_month, cycle.best_buy_day)

    if cycle.due_day > cycle.best_buy_day:
        due_year, due_month = closing_year, closing_month
    else:
        due_year, due_month = shift_month(closing_year, closing_month, 1)
    return Statement(closing_date, clamp_date(due_year, due_month, cycle.due_day))
