from app.utils.pydantic_expense import ExpenseCreate
from app.utils.pydantic_income import IncomeCreate

def handle_installments_split(entry: ExpenseCreate | IncomeCreate) -> list[IncomeCreate | ExpenseCreate]:
    installments = entry.installments
    amount_per_entry = entry.amount / installments

    entries = []
    entry_type = type(entry)

    for i in range(installments):
        entry_dict = entry.model_dump()
        entry_dict["amount"] = amount_per_entry
        entry_dict["installments"] = f"{i + 1}/{installments}"

        entries.append(entry_type(**entry_dict))

    return entries