"""Recurrence, the template behind fixed entries (specs/schemas.md §12)."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import ARRAY, CheckConstraint, Date, ForeignKey, SmallInteger, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, str_enum
from app.domain.enums import Currency, EntryType, PaymentMethod


class Recurrence(UUIDPk, Timestamps, Base):
    __tablename__ = "recurrences"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("interval_months BETWEEN 1 AND 12", name="interval_range"),
        CheckConstraint("day_of_month BETWEEN 1 AND 31", name="day_range"),
        CheckConstraint("end_date IS NULL OR end_date >= start_date", name="end_after_start"),
        CheckConstraint("type = 'EXPENSE' OR card_id IS NULL", name="card_only_for_expense"),
        CheckConstraint(
            "type = 'INCOME' OR (payment_method IN ('CREDIT', 'DEBIT')) = (card_id IS NOT NULL)",
            name="card_matches_method",
        ),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), index=True)
    type: Mapped[EntryType] = mapped_column(str_enum(EntryType, "entry_type"))
    person_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[Decimal]
    currency: Mapped[Currency] = mapped_column(str_enum(Currency, "currency"))
    payment_method: Mapped[PaymentMethod] = mapped_column(str_enum(PaymentMethod, "payment_method"))
    card_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cards.id"))
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id"))
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id"))
    description: Mapped[str | None] = mapped_column(String(200))
    interval_months: Mapped[int] = mapped_column(SmallInteger, default=1)
    day_of_month: Mapped[int] = mapped_column(SmallInteger)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    skipped_dates: Mapped[list[date]] = mapped_column(
        ARRAY(Date), default=list, server_default=text("'{}'")
    )
    is_active: Mapped[bool] = mapped_column(default=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
