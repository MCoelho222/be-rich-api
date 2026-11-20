"""Read models for the dashboard (specs/api.md §13)."""

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_now
from app.core.clock import today
from app.db.session import get_db
from app.domain.enums import EntryType
from app.schemas.entries import ExpenseOut, IncomeOut
from app.schemas.reports import (
    BalancesOut,
    CardBillsOut,
    CategoriesOut,
    ProjectedOccurrenceOut,
    ProjectionItemOut,
    ProjectionItemsOut,
    ProjectionOut,
    SummaryOut,
)
from app.services import reports as svc
from app.services.auth import CurrentUser
from app.services.fx_provider import RateProvider, get_rate_provider

router = APIRouter(tags=["read models"])


class Context:
    """What every read-model request needs: today, the filters and a converter."""

    def __init__(
        self,
        account_id: uuid.UUID | None = None,
        member_id: uuid.UUID | None = None,
        current: CurrentUser = Depends(get_current_user),
        db: Session = Depends(get_db),
        provider: RateProvider = Depends(get_rate_provider),
        now: datetime = Depends(get_now),
    ) -> None:
        self.db = db
        self.household_id = current.household.id
        self.today = today()
        self.filters = svc.Filters(account_id=account_id, member_id=member_id)
        svc.check_filters(db, self.household_id, self.filters)
        self.conv = svc.Converter(db, provider, current.household.default_currency, self.today, now)

    def done(self) -> None:
        # Historical rates fetched on demand are cached for good (operations.md §2.3).
        self.db.commit()


FROM = Query(alias="from")


@router.get("/balances", response_model=BalancesOut)
def get_balances(date_: date | None = Query(None, alias="date"), include_archived: bool = True,
                 ctx: Context = Depends()):  # fmt: skip
    if ctx.filters.member_id is not None:
        ctx.filters = svc.Filters(account_id=ctx.filters.account_id)  # balances are never per member
    result = svc.balances(ctx.db, ctx.household_id, date_ or ctx.today, ctx.today, ctx.conv,
                          ctx.filters.account_id, include_archived)  # fmt: skip
    ctx.done()
    return result


@router.get("/dashboard/summary", response_model=SummaryOut)
def get_summary(start: date = FROM, to: date = Query(), ctx: Context = Depends()):
    svc.check_range(start, to)
    result = svc.summary(ctx.db, ctx.household_id, start, to, ctx.today, ctx.filters, ctx.conv)
    ctx.done()
    return result


@router.get("/projection", response_model=ProjectionOut)
def get_projection(start: date = FROM, to: date = Query(), ctx: Context = Depends()):
    result = svc.projection(ctx.db, ctx.household_id, start, to, ctx.today, ctx.filters, ctx.conv)
    ctx.done()
    return result


@router.get("/dashboard/categories", response_model=CategoriesOut)
def get_categories(start: date = FROM, to: date = Query(), type: EntryType = EntryType.EXPENSE,  # noqa: A002
                   ctx: Context = Depends()):  # fmt: skip
    svc.check_range(start, to)
    result = svc.categories(ctx.db, ctx.household_id, start, to, ctx.today, type, ctx.filters, ctx.conv)
    ctx.done()
    return result


@router.get("/cards/bills", response_model=CardBillsOut)
def get_card_bills(ctx: Context = Depends()):
    result = svc.card_bills(ctx.db, ctx.household_id, ctx.today, ctx.filters, ctx.conv)
    ctx.done()
    return result


def item_out(line: svc.Line) -> ProjectionItemOut:
    occurrence = None
    if line.recurrence is not None:
        rec = line.recurrence
        occurrence = ProjectedOccurrenceOut(
            recurrence_id=rec.id, occurrence_date=line.occurrence_date, status=line.occurrence_status,
            description=rec.description, category_id=rec.category_id, account_id=rec.account_id,
            card_id=rec.card_id, person_id=rec.person_id, payment_method=rec.payment_method,
        )  # fmt: skip
    row = None
    if line.row is not None:
        row = (ExpenseOut if line.type is EntryType.EXPENSE else IncomeOut).model_validate(line.row)
    return ProjectionItemOut(
        type=line.type, projected=line.projected, payment_date=line.payment_date, amount=line.amount,
        currency=line.currency, converted=line.converted, row=row, occurrence=occurrence,
    )  # fmt: skip


@router.get("/projection/items", response_model=ProjectionItemsOut)
def get_projection_items(
    start: date = FROM,
    to: date = Query(),
    type: EntryType | None = None,  # noqa: A002 - API parameter name
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    ctx: Context = Depends(),
):
    svc.check_range(start, to)
    lines, next_cursor = svc.projection_items(
        ctx.db, ctx.household_id, start, to, ctx.today, ctx.filters, ctx.conv, type, order == "desc", limit, cursor
    )
    items = [item_out(line) for line in lines]
    ctx.done()
    return {**ctx.conv.meta(), "items": items, "next_cursor": next_cursor}
