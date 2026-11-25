"""Expenses and incomes (specs/api.md §10-§11). One router factory serves both."""

import uuid
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.clock import today
from app.db.session import get_db
from app.domain.enums import EditScope, PaymentMethod
from app.domain.money import round_money
from app.schemas.entries import (
    ExpenseCreate,
    ExpenseOut,
    ExpensePatch,
    IncomeCreate,
    IncomeOut,
    IncomePatch,
    MoneyObj,
    PlannedRowOut,
    PreviewOut,
)
from app.services import entries as svc
from app.services.auth import CurrentUser
from app.services.fx import latest_rate


def _page_model(out: type[BaseModel], name: str) -> type[BaseModel]:
    return type(name, (BaseModel,), {"__annotations__": {"items": list[out], "next_cursor": str | None}})


def _items_model(out: type[BaseModel], name: str, with_split: bool) -> type[BaseModel]:
    annotations: dict[str, Any] = {"items": list[out]}
    namespace: dict[str, Any] = {"__annotations__": annotations}
    if with_split:
        annotations["split_group_id"] = uuid.UUID | None
    return type(name, (BaseModel,), namespace)


def build_router(
    kind: svc.Kind,
    prefix: str,
    create_model: type[BaseModel],
    patch_model: type[BaseModel],
    out_model: type[BaseModel],
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=[prefix.strip("/")])
    title = kind.entry_type.value.capitalize()
    Page = _page_model(out_model, f"{title}Page")
    Created = _items_model(out_model, f"{title}Created", with_split=True)
    Affected = _items_model(out_model, f"{title}Affected", with_split=False)

    def preview_body(plan: svc.PurchasePlan, household, db: Session) -> PreviewOut:
        items = [
            PlannedRowOut(
                part=i, transaction_date=plan.transaction_date, payment_date=r.payment_date, amount=r.amount,
                currency=plan.currency, payment_method=part.payment.method,
                card_id=part.payment.card.id if part.payment.card else None, account_id=part.payment.account.id,
                installment_number=r.installment_number, installment_total=r.installment_total,
            )  # fmt: skip
            for i, part in enumerate(plan.parts)
            for r in part.rows
        ]
        converted = None
        if plan.currency != household.default_currency:
            found = latest_rate(db, plan.currency, household.default_currency)
            if found is not None:
                rate, _ = found
                converted = MoneyObj(amount=round_money(plan.total * rate), currency=household.default_currency)
        return PreviewOut(items=items, converted_total=converted)

    @router.get("", response_model=Page)
    def list_rows(
        from_: date | None = Query(None, alias="from"),
        to: date | None = None,
        date_field: Literal["payment_date", "transaction_date"] = "payment_date",
        account_id: uuid.UUID | None = None,
        card_id: uuid.UUID | None = None,
        category_id: uuid.UUID | None = None,
        person_id: uuid.UUID | None = Query(None, alias=kind.person_field),
        payment_method: PaymentMethod | None = None,
        recurrence_id: uuid.UUID | None = None,
        fixed_only: bool = False,
        installment_group_id: uuid.UUID | None = None,
        split_group_id: uuid.UUID | None = None,
        q: str | None = Query(None, max_length=100),
        limit: int = Query(50, ge=1, le=200),
        cursor: str | None = Query(None, max_length=500),
        current: CurrentUser = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        filters = svc.ListFilters(
            start=from_, end=to, date_field=date_field, account_id=account_id, card_id=card_id,
            category_id=category_id, person_id=person_id, payment_method=payment_method,
            recurrence_id=recurrence_id, fixed_only=fixed_only, installment_group_id=installment_group_id,
            split_group_id=split_group_id, q=q,
        )  # fmt: skip
        rows, next_cursor = svc.list_rows(db, kind, current.household.id, filters, limit, cursor)
        return {"items": rows, "next_cursor": next_cursor}

    @router.get("/{row_id}", response_model=out_model)
    def get_row(row_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
        return svc.get_row(db, kind, current.household.id, row_id)

    @router.post("/preview", response_model=PreviewOut)
    def preview(body: create_model, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):  # type: ignore[valid-type]
        plan = svc.plan_purchase(db, kind, current.household, current.user, body, today())
        return preview_body(plan, current.household, db)

    @router.post("", status_code=status.HTTP_201_CREATED, response_model=Created)
    def create(body: create_model, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):  # type: ignore[valid-type]
        plan = svc.plan_purchase(db, kind, current.household, current.user, body, today())
        split_group_id, rows = svc.create_purchase(db, kind, current.household, current.user, plan)
        db.commit()
        return {"split_group_id": split_group_id, "items": rows}

    @router.patch("/{row_id}", response_model=Affected)
    def update(
        row_id: uuid.UUID,
        body: patch_model,  # type: ignore[valid-type]
        scope: EditScope | None = None,
        current: CurrentUser = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        row = svc.get_row(db, kind, current.household.id, row_id)
        changes = {f: getattr(body, f) for f in body.model_fields_set}
        if kind.person_field in changes:
            changes["person_id"] = changes.pop(kind.person_field)
        rows = svc.update_entry(db, kind, current.household, row, changes, scope)
        db.commit()
        return {"items": rows}

    @router.delete("/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete(
        row_id: uuid.UUID,
        scope: EditScope | None = None,
        current: CurrentUser = Depends(get_current_user),
        db: Session = Depends(get_db),
    ):
        svc.delete_entry(db, kind, svc.get_row(db, kind, current.household.id, row_id), scope)
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


expenses_router = build_router(svc.EXPENSE, "/expenses", ExpenseCreate, ExpensePatch, ExpenseOut)
incomes_router = build_router(svc.INCOME, "/incomes", IncomeCreate, IncomePatch, IncomeOut)
