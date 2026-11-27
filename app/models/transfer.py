"""Transfer (specs/schemas.md §21).

Money moved between two accounts, or between an account and an investment. Each end is
an account or an investment; an investment end keeps a label so the row still reads
after the investment is deleted.
"""

import uuid
import datetime as dt
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, str_enum
from app.domain.enums import Currency, TransferEnd


def _end_checks(end: str) -> tuple:
    return (
        CheckConstraint(
            f"({end}_kind = 'ACCOUNT' AND {end}_account_id IS NOT NULL AND {end}_investment_id IS NULL)"
            f" OR ({end}_kind = 'INVESTMENT' AND {end}_account_id IS NULL AND {end}_label IS NOT NULL)",
            name=f"{end}_matches_kind",
        ),
    )


class Transfer(UUIDPk, Timestamps, Base):
    __tablename__ = "transfers"
    __table_args__ = (
        CheckConstraint("amount_sent > 0", name="amount_sent_positive"),
        CheckConstraint("amount_received > 0", name="amount_received_positive"),
        CheckConstraint(
            "from_account_id IS DISTINCT FROM to_account_id OR from_account_id IS NULL",
            name="distinct_accounts",
        ),
        CheckConstraint(
            "from_investment_id IS DISTINCT FROM to_investment_id OR from_investment_id IS NULL",
            name="distinct_investments",
        ),
        *_end_checks("from"),
        *_end_checks("to"),
        Index("ix_transfers_household_date", "household_id", "date"),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"))
    date: Mapped[dt.date] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String(200))

    from_kind: Mapped[TransferEnd] = mapped_column(str_enum(TransferEnd, "from_kind"))
    from_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id"), index=True
    )
    from_investment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("investments.id", ondelete="SET NULL"), index=True
    )
    from_label: Mapped[str | None] = mapped_column(String(84))
    amount_sent: Mapped[Decimal]
    currency_sent: Mapped[Currency] = mapped_column(str_enum(Currency, "currency_sent"))

    to_kind: Mapped[TransferEnd] = mapped_column(str_enum(TransferEnd, "to_kind"))
    to_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id"), index=True
    )
    to_investment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("investments.id", ondelete="SET NULL"), index=True
    )
    to_label: Mapped[str | None] = mapped_column(String(84))
    amount_received: Mapped[Decimal]
    currency_received: Mapped[Currency] = mapped_column(
        str_enum(Currency, "currency_received")
    )

    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
