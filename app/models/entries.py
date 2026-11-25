"""Expense and Income rows (specs/schemas.md §10-§11).

Each row is one payment, with one method, from or into one account, on one date.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, str_enum
from app.domain.enums import Currency, PaymentMethod


def _entry_constraints(table: str) -> tuple:
    return (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("installment_total BETWEEN 1 AND 60", name="installment_total_range"),
        CheckConstraint(
            "installment_number BETWEEN 1 AND installment_total", name="installment_number_range"
        ),
        # A series id exists exactly when there is more than one installment
        CheckConstraint(
            "(installment_total = 1) = (installment_group_id IS NULL)", name="installment_group"
        ),
        # recurrence_id and occurrence_date are set together (§10)
        CheckConstraint(
            "(recurrence_id IS NULL) = (occurrence_date IS NULL)", name="occurrence_pair"
        ),
        # Registered occurrences are single rows, never split (§10.1 rule 6, §10.5)
        CheckConstraint(
            "recurrence_id IS NULL OR (installment_total = 1 AND split_group_id IS NULL)",
            name="occurrence_single_row",
        ),
        # Each occurrence can be registered at most once (§12.1)
        UniqueConstraint("recurrence_id", "occurrence_date", name=f"uq_{table}_recurrence_occurrence"),
        Index(f"ix_{table}_household_payment_date", "household_id", "payment_date"),
    )


class _EntryColumns(UUIDPk, Timestamps):
    """Columns shared by Expense and Income."""

    @declared_attr
    def household_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(ForeignKey("households.id"))

    transaction_date: Mapped[date] = mapped_column(Date)
    payment_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal]
    currency: Mapped[Currency] = mapped_column(str_enum(Currency, "currency"))
    payment_method: Mapped[PaymentMethod] = mapped_column(str_enum(PaymentMethod, "payment_method"))

    @declared_attr
    def account_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(ForeignKey("accounts.id"), index=True)

    @declared_attr
    def category_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(ForeignKey("categories.id"))

    description: Mapped[str | None] = mapped_column(String(200))
    installment_number: Mapped[int] = mapped_column(SmallInteger, default=1)
    installment_total: Mapped[int] = mapped_column(SmallInteger, default=1)
    installment_group_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    split_group_id: Mapped[uuid.UUID | None] = mapped_column(index=True)

    @declared_attr
    def recurrence_id(cls) -> Mapped[uuid.UUID | None]:
        return mapped_column(ForeignKey("recurrences.id"))

    occurrence_date: Mapped[date | None] = mapped_column(Date)

    @declared_attr
    def created_by_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(ForeignKey("users.id"))


class Expense(_EntryColumns, Base):
    __tablename__ = "expenses"
    __table_args__ = (
        *_entry_constraints("expenses"),
        # A card exactly for CREDIT and DEBIT (§10)
        CheckConstraint(
            "(payment_method IN ('CREDIT', 'DEBIT')) = (card_id IS NOT NULL)",
            name="card_matches_method",
        ),
        CheckConstraint(
            "payment_method <> 'DEBIT' OR installment_total = 1", name="debit_single_installment"
        ),
    )

    spender_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    card_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cards.id"), index=True)


class Income(_EntryColumns, Base):
    __tablename__ = "incomes"
    __table_args__ = _entry_constraints("incomes")

    receiver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
