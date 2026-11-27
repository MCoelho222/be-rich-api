"""Investments and their share of the household balance (specs/schemas.md §20)."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.errors import validation_error
from app.domain.enums import Liquidity
from app.models import Household, Investment
from app.schemas.common import blank_to_none
from app.schemas.investments import InvestmentCreate, InvestmentPatch

REQUIRED = ("bank", "amount", "currency", "invested_on", "liquidity", "include_in_balance")


def list_investments(db: Session, household_id: uuid.UUID) -> list[Investment]:
    return list(
        db.scalars(
            select(Investment)
            .where(Investment.household_id == household_id)
            .order_by(Investment.maturity_date.asc().nulls_first(), func.lower(Investment.bank), Investment.created_at)
        )
    )


def _validate(investment: Investment, creating: bool = False) -> None:
    """Rules checked on the final values, so create and patch share them. Transfers can
    redeem an investment down to 0 (§21), so only a new one must hold more than 0."""
    errors: dict[str, list[str]] = {}
    if creating and investment.amount <= 0:
        errors["amount"] = ["Must be greater than zero"]
    elif investment.amount < 0:
        errors["amount"] = ["Can't be negative"]
    if investment.liquidity is Liquidity.MATURITY:
        if investment.maturity_date is None:
            errors["maturity_date"] = ["Required when liquidity is MATURITY"]
        elif investment.maturity_date <= investment.invested_on:
            errors["maturity_date"] = ["Must be after the investment date"]
    elif investment.maturity_date is not None:
        errors["maturity_date"] = ["Must be empty when liquidity is DAILY"]
    if errors:
        raise validation_error(errors)


def create_investment(db: Session, household: Household, body: InvestmentCreate, today: date) -> Investment:
    investment = Investment(
        household_id=household.id,
        name=blank_to_none(body.name),
        bank=body.bank,
        amount=body.amount,
        currency=body.currency or household.default_currency,
        invested_on=body.invested_on or today,
        liquidity=body.liquidity,
        maturity_date=body.maturity_date,
        include_in_balance=body.include_in_balance,
    )
    _validate(investment, creating=True)
    db.add(investment)
    db.flush()
    return investment


def update_investment(db: Session, investment: Investment, body: InvestmentPatch) -> None:
    sent = body.model_fields_set
    missing = {f: ["Can't be empty"] for f in REQUIRED if f in sent and getattr(body, f) is None}
    if missing:
        raise validation_error(missing)
    for field in sent:
        value = getattr(body, field)
        setattr(investment, field, blank_to_none(value) if field == "name" else value)
    # Switching to daily liquidity drops the due date without the client having to send null.
    if "liquidity" in sent and body.liquidity is Liquidity.DAILY and "maturity_date" not in sent:
        investment.maturity_date = None
    _validate(investment)
    db.flush()


class InvestmentBook:
    """The investments counted in the household balance (§20.1), loaded once so that
    balances on many dates (one per projection month) don't reload anything."""

    def __init__(self, db: Session, household_id: uuid.UUID) -> None:
        self.items = list(
            db.scalars(
                select(Investment).where(
                    Investment.household_id == household_id, Investment.include_in_balance.is_(True)
                )
            )
        )

    def held(self, day: date) -> list[Investment]:
        return [i for i in self.items if i.invested_on <= day]

    @staticmethod
    def total(items: list[Investment], convert) -> Decimal | None:
        """Sum in the household currency; None when nothing is held."""
        if not items:
            return None
        return sum((convert(i) or Decimal("0") for i in items), Decimal("0"))
