"""Transfers between accounts and investments (specs/schemas.md §21).

A transfer moves an account's balance on its date, like a payment, and changes an
investment's amount right away, which is why its date can't be in the future.
"""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.errors import ApiError, validation_error
from app.domain.enums import Currency, TransferEnd
from app.models import Account, Household, Investment, Transfer, User
from app.schemas.common import blank_to_none
from app.schemas.transfers import (
    TransferCreate,
    TransferEndIn,
    TransferEndOut,
    TransferOut,
)
from app.services.reference import get_owned


@dataclass(frozen=True)
class End:
    kind: TransferEnd
    account: Account | None = None
    investment: Investment | None = None

    @property
    def currency(self) -> Currency:
        return self.account.currency if self.account else self.investment.currency


def investment_label(investment: Investment) -> str:
    return investment.name or investment.bank


def _resolve(db: Session, household_id: uuid.UUID, end: TransferEndIn) -> End:
    if end.kind is TransferEnd.ACCOUNT:
        return End(end.kind, account=get_owned(db, Account, household_id, end.id))
    return End(end.kind, investment=get_owned(db, Investment, household_id, end.id))


def _columns(prefix: str, end: End) -> dict:
    return {
        f"{prefix}_kind": end.kind,
        f"{prefix}_account_id": end.account.id if end.account else None,
        f"{prefix}_investment_id": end.investment.id if end.investment else None,
        f"{prefix}_label": investment_label(end.investment) if end.investment else None,
    }


def create_transfer(
    db: Session, household: Household, caller: User, body: TransferCreate, today: date
) -> Transfer:
    source = _resolve(db, household.id, body.source)
    target = _resolve(db, household.id, body.target)
    errors: dict[str, list[str]] = {}
    if body.source == body.target:
        errors["target"] = ["Must be different from the source"]
    if body.amount <= 0:
        errors["amount"] = ["Must be greater than zero"]
    elif source.investment is not None and body.amount > source.investment.amount:
        errors["amount"] = [
            f"Can't be more than the investment's amount ({source.investment.amount})"
        ]
    same_currency = source.currency == target.currency
    received = body.amount if same_currency else body.amount_received
    if not same_currency:
        if received is None:
            errors["amount_received"] = ["Required when the currencies differ"]
        elif received <= 0:
            errors["amount_received"] = ["Must be greater than zero"]
    on = body.date or today
    if on > today:
        errors["date"] = ["Can't be in the future"]
    if errors:
        raise validation_error(errors)

    if source.investment is not None:
        source.investment.amount -= body.amount
    if target.investment is not None:
        target.investment.amount += received
    transfer = Transfer(
        household_id=household.id,
        date=on,
        description=blank_to_none(body.description),
        amount_sent=body.amount,
        currency_sent=source.currency,
        amount_received=received,
        currency_received=target.currency,
        created_by_id=caller.id,
        **_columns("from", source),
        **_columns("to", target),
    )
    db.add(transfer)
    db.flush()
    return transfer


def delete_transfer(db: Session, transfer: Transfer) -> None:
    """Undo the transfer, giving back what it took from or added to investments that still exist."""
    if transfer.to_investment_id is not None:
        target = db.get(Investment, transfer.to_investment_id)
        if target.amount < transfer.amount_received:
            raise ApiError(
                409,
                "CONFLICT",
                "The investment no longer holds this amount, so the transfer can't be undone.",
            )
        target.amount -= transfer.amount_received
    if transfer.from_investment_id is not None:
        db.get(Investment, transfer.from_investment_id).amount += transfer.amount_sent
    db.delete(transfer)
    db.flush()


def list_transfers(
    db: Session, household_id: uuid.UUID, start: date | None, end: date | None,
    account_id: uuid.UUID | None, investment_id: uuid.UUID | None,
) -> list[Transfer]:  # fmt: skip
    stmt = select(Transfer).where(Transfer.household_id == household_id)
    if start is not None:
        stmt = stmt.where(Transfer.date >= start)
    if end is not None:
        stmt = stmt.where(Transfer.date <= end)
    if account_id is not None:
        stmt = stmt.where(
            or_(
                Transfer.from_account_id == account_id,
                Transfer.to_account_id == account_id,
            )
        )
    if investment_id is not None:
        stmt = stmt.where(
            or_(
                Transfer.from_investment_id == investment_id,
                Transfer.to_investment_id == investment_id,
            )
        )
    return list(
        db.scalars(stmt.order_by(Transfer.date.desc(), Transfer.created_at.desc()))
    )


def account_transfers(
    db: Session, account_ids, until: date
) -> list[tuple[uuid.UUID, Currency, date, Decimal]]:
    """Signed account movements from transfers up to `until`: (account, currency, date, amount)."""
    moves = []
    rows = db.scalars(
        select(Transfer).where(
            or_(
                Transfer.from_account_id.in_(account_ids),
                Transfer.to_account_id.in_(account_ids),
            ),
            Transfer.date <= until,
        )
    )
    for t in rows:
        if t.from_account_id is not None:
            moves.append((t.from_account_id, t.currency_sent, t.date, -t.amount_sent))
        if t.to_account_id is not None:
            moves.append(
                (t.to_account_id, t.currency_received, t.date, t.amount_received)
            )
    return moves


def transfer_out(transfer: Transfer) -> TransferOut:
    def end(prefix: str) -> TransferEndOut:
        return TransferEndOut(
            kind=getattr(transfer, f"{prefix}_kind"),
            account_id=getattr(transfer, f"{prefix}_account_id"),
            investment_id=getattr(transfer, f"{prefix}_investment_id"),
            label=getattr(transfer, f"{prefix}_label"),
        )

    return TransferOut(
        id=transfer.id, date=transfer.date, description=transfer.description,
        source=end("from"), target=end("to"),
        amount_sent=transfer.amount_sent, currency_sent=transfer.currency_sent,
        amount_received=transfer.amount_received, currency_received=transfer.currency_received,
        created_at=transfer.created_at,
    )  # fmt: skip
