"""Household creation and its seed data (specs/schemas.md §4.1, §9)."""

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.enums import AccountType, Currency, EntryType, Language
from app.models import Account, Category, Household

# Created in the user's language. Each one keeps a `seed_key` until it is renamed, so the UI
# can show it in the language the user picks (§9); afterwards it is ordinary user data.
SEED_CATEGORIES: dict[EntryType, tuple[tuple[str, str, str], ...]] = {
    EntryType.EXPENSE: (
        ("food", "Food", "Alimentação"), ("gasoline", "Gasoline", "Combustível"), ("car", "Car", "Carro"),
        ("house", "House", "Casa"), ("rent", "Rent", "Aluguel"), ("courses", "Courses", "Cursos"),
        ("music", "Music", "Música"), ("clothes", "Clothes", "Roupas"), ("health", "Health", "Saúde"),
        ("pharmacy", "Pharmacy", "Farmácia"), ("gym", "Gym", "Academia"), ("kids", "Kids", "Filhos"),
        ("trips", "Trips", "Viagens"), ("transport", "Transport", "Transporte"),
        ("entertainment", "Entertainment", "Lazer"), ("birthdays", "Birthdays", "Aniversários"),
        ("gas", "Gas", "Gás"), ("electricity", "Electricity", "Energia"), ("internet", "Internet", "Internet"),
        ("ai", "AI", "IA"), ("storage", "Storage", "Armazenamento"), ("phone", "Phone", "Telefone"),
        ("business", "Business", "Negócios"), ("tax", "Tax", "Impostos"), ("other", "Other", "Outros"),
    ),
    EntryType.INCOME: (
        ("salary", "Salary", "Salário"), ("investments", "Investments", "Investimentos"),
        ("other", "Other", "Outros"),
    ),
}  # fmt: skip


def seed_name(entry: tuple[str, str, str], language: Language) -> str:
    return entry[2] if language is Language.PT else entry[1]


DEFAULT_EXPENSE_CATEGORIES: dict[Language, tuple[str, ...]] = {
    language: tuple(seed_name(e, language) for e in SEED_CATEGORIES[EntryType.EXPENSE]) for language in Language
}

CASH_ACCOUNT_NAME = {Language.EN: "Cash", Language.PT: "Dinheiro"}


def household_name_for(person_name: str, language: Language = Language.EN) -> str:
    first_name = person_name.strip().split()[0]
    name = f"Casa de {first_name}" if language is Language.PT else f"{first_name}'s household"
    return name[:60]


def create_household(
    db: Session,
    *,
    person_name: str,
    today: date,
    default_currency: Currency = Currency.BRL,
    language: Language = Language.EN,
) -> Household:
    """Create a household with its default expense and income categories and a Cash account.

    Used at signup without an invitation and when a member leaves or is removed
    (§4.2). Only flushes: the caller owns the transaction.
    """
    household = Household(name=household_name_for(person_name, language), default_currency=default_currency)
    db.add(household)
    db.flush()

    db.add_all(
        Category(household_id=household.id, type=entry_type, name=seed_name(entry, language), seed_key=entry[0])
        for entry_type, entries in SEED_CATEGORIES.items()
        for entry in entries
    )
    db.add(
        Account(
            household_id=household.id,
            type=AccountType.CASH,
            name=CASH_ACCOUNT_NAME[language],
            currency=default_currency,
            opening_balance=Decimal("0.00"),
            opening_balance_date=today,
        )
    )
    db.flush()
    return household
