from datetime import datetime
from app.models.Expense import Expense, ExpenseFixed
from app.models.Income import Income, IncomeFixed


def add_months(date: datetime, months: int) -> datetime:
    """Add months to a datetime, handling year rollover."""
    month = date.month - 1 + months
    year = date.year + month // 12
    month = month % 12 + 1
    day = min(date.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date.replace(year=year, month=month, day=day)


def handle_installments_split(entry: Expense | ExpenseFixed | Income | IncomeFixed, installments: int) -> list[Expense | ExpenseFixed | Income | IncomeFixed]:
    amount_per_entry = entry.amount / installments

    entries = []
    entry_type = type(entry)

    for i in range(installments):
        entry_dict = entry.model_dump(exclude={'id', 'updated_at'})
        entry_dict["amount"] = amount_per_entry
        entry_dict["installment"] = f"{i + 1}/{installments}"
        entry_dict["created_at"] = add_months(entry.created_at, i)

        entries.append(entry_type(**entry_dict))

    return entries