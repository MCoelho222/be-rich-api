"""Investment (specs/schemas.md §20)."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, str_enum
from app.domain.enums import Currency, Liquidity


class Investment(UUIDPk, Timestamps, Base):
    __tablename__ = "investments"
    __table_args__ = (
        # 0 once fully redeemed by transfers (§21); a new investment still needs more than 0.
        CheckConstraint("amount >= 0", name="amount_positive"),
        CheckConstraint(
            "(liquidity = 'DAILY' AND maturity_date IS NULL)"
            " OR (liquidity = 'MATURITY' AND maturity_date IS NOT NULL AND maturity_date > invested_on)",
            name="maturity_matches_liquidity",
        ),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), index=True)
    name: Mapped[str | None] = mapped_column(String(40))
    bank: Mapped[str] = mapped_column(String(40))
    amount: Mapped[Decimal]
    currency: Mapped[Currency] = mapped_column(str_enum(Currency, "currency"))
    invested_on: Mapped[date] = mapped_column(Date)
    liquidity: Mapped[Liquidity] = mapped_column(str_enum(Liquidity, "liquidity"))
    maturity_date: Mapped[date | None] = mapped_column(Date)
    include_in_balance: Mapped[bool] = mapped_column(default=True)
