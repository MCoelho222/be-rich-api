"""Account, Card and Category (specs/schemas.md §7-§9)."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, SmallInteger, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, str_enum
from app.domain.enums import AccountType, CardType, Currency, EntryType


class Account(UUIDPk, Timestamps, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        Index("uq_accounts_household_name", "household_id", func.lower(text("name")), unique=True),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), index=True)
    type: Mapped[AccountType] = mapped_column(str_enum(AccountType, "account_type"))
    name: Mapped[str] = mapped_column(String(40))
    currency: Mapped[Currency] = mapped_column(str_enum(Currency, "currency"))
    opening_balance: Mapped[Decimal] = mapped_column(default=Decimal("0.00"))
    opening_balance_date: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(default=True)


class Card(UUIDPk, Timestamps, Base):
    __tablename__ = "cards"
    __table_args__ = (
        Index("uq_cards_household_alias", "household_id", func.lower(text("alias")), unique=True),
        CheckConstraint(r"alias ~ '^[A-Za-z0-9_-]+$'", name="alias_single_word"),
        CheckConstraint(r"last_four ~ '^[0-9]{4}$'", name="last_four_digits"),
        CheckConstraint("best_buy_day BETWEEN 1 AND 31", name="best_buy_day_range"),
        CheckConstraint("due_day BETWEEN 1 AND 31", name="due_day_range"),
        # Credit cards need both days; debit-only cards have neither (§8)
        CheckConstraint(
            "(type = 'DEBIT' AND best_buy_day IS NULL AND due_day IS NULL)"
            " OR (type <> 'DEBIT' AND best_buy_day IS NOT NULL AND due_day IS NOT NULL)",
            name="credit_days",
        ),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    alias: Mapped[str] = mapped_column(String(20))
    type: Mapped[CardType] = mapped_column(str_enum(CardType, "card_type"), default=CardType.CREDIT)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    last_four: Mapped[str | None] = mapped_column(String(4))
    best_buy_day: Mapped[int | None] = mapped_column(SmallInteger)
    due_day: Mapped[int | None] = mapped_column(SmallInteger)
    is_active: Mapped[bool] = mapped_column(default=True)


class Category(UUIDPk, Timestamps, Base):
    __tablename__ = "categories"
    __table_args__ = (
        Index(
            "uq_categories_household_type_name",
            "household_id",
            "type",
            func.lower(text("name")),
            unique=True,
        ),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), index=True)
    type: Mapped[EntryType] = mapped_column(str_enum(EntryType, "entry_type"))
    name: Mapped[str] = mapped_column(String(30))
    # A built-in category keeps its key until renamed; the UI translates it (schemas §9).
    seed_key: Mapped[str | None] = mapped_column(String(30), default=None)
    is_active: Mapped[bool] = mapped_column(default=True)
