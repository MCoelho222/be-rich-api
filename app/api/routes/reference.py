"""Accounts, cards and categories (specs/api.md §7-§9)."""

import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.clock import today
from app.db.session import get_db
from app.domain.business_days import next_business_day
from app.domain.credit import CardCycle, statement_for_purchase
from app.domain.enums import EntryType
from app.models import Account, Card, Category
from app.schemas.common import Items
from app.schemas.reference import (
    AccountAdjust,
    AccountCreate,
    AccountOut,
    AccountPatch,
    CardCreate,
    CardOut,
    CardPatch,
    CardPreviewIn,
    CardPreviewOut,
    CategoryCreate,
    CategoryOut,
    CategoryPatch,
)
from app.services import reference as svc
from app.services.auth import CurrentUser
from app.services.calendar import holidays_around

router = APIRouter()
NO_CONTENT = status.HTTP_204_NO_CONTENT


def _no_content() -> Response:
    return Response(status_code=NO_CONTENT)


# --- Accounts ----------------------------------------------------------------------

accounts = APIRouter(prefix="/accounts", tags=["accounts"])


@accounts.get("", response_model=Items[AccountOut])
def list_accounts(
    include_archived: bool = False,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return Items(items=svc.list_accounts(db, current.household.id, include_archived))


@accounts.post("", status_code=status.HTTP_201_CREATED, response_model=AccountOut)
def create_account(body: AccountCreate, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    account = svc.create_account(db, current.household, body, today())
    db.commit()
    return account


@accounts.patch("/{account_id}", response_model=AccountOut)
def update_account(
    account_id: uuid.UUID,
    body: AccountPatch,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = svc.get_owned(db, Account, current.household.id, account_id)
    svc.update_account(db, account, body)
    db.commit()
    return account


@accounts.post("/{account_id}/adjust", response_model=AccountOut)
def adjust_account(
    account_id: uuid.UUID,
    body: AccountAdjust,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = svc.get_owned(db, Account, current.household.id, account_id)
    svc.adjust_account(db, account, body.balance, body.date or today())
    db.commit()
    return account


@accounts.post("/{account_id}/archive", response_model=AccountOut)
def archive_account(account_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    account = svc.get_owned(db, Account, current.household.id, account_id)
    svc.archive_account(db, account)
    db.commit()
    return account


@accounts.post("/{account_id}/unarchive", response_model=AccountOut)
def unarchive_account(account_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    account = svc.get_owned(db, Account, current.household.id, account_id)
    svc.set_active(db, account, True)
    db.commit()
    return account


@accounts.delete("/{account_id}", status_code=NO_CONTENT)
def delete_account(account_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    svc.delete_account(db, svc.get_owned(db, Account, current.household.id, account_id))
    db.commit()
    return _no_content()


# --- Cards -------------------------------------------------------------------------

cards = APIRouter(prefix="/cards", tags=["cards"])


@cards.get("", response_model=Items[CardOut])
def list_cards(
    include_archived: bool = False,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return Items(items=svc.list_cards(db, current.household.id, include_archived))


@cards.post("/preview", response_model=CardPreviewOut)
def preview_card(body: CardPreviewIn, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    """Due date for a purchase, before the card exists (ui-behavior §5 live preview)."""
    purchase = body.purchase_date or today()
    statement = statement_for_purchase(purchase, CardCycle(body.best_buy_day, body.due_day))
    holidays = holidays_around(db, purchase, statement.nominal_due_date)
    return CardPreviewOut(
        closing_date=statement.closing_date,
        payment_date=next_business_day(statement.nominal_due_date, holidays),
    )


@cards.post("", status_code=status.HTTP_201_CREATED, response_model=CardOut)
def create_card(body: CardCreate, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    card = svc.create_card(db, current.household.id, current.user, body)
    db.commit()
    return card


@cards.patch("/{card_id}", response_model=CardOut)
def update_card(
    card_id: uuid.UUID,
    body: CardPatch,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    card = svc.get_owned(db, Card, current.household.id, card_id)
    svc.update_card(db, card, body)
    db.commit()
    return card


@cards.post("/{card_id}/archive", response_model=CardOut)
def archive_card(card_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    card = svc.get_owned(db, Card, current.household.id, card_id)
    svc.set_active(db, card, False)
    db.commit()
    return card


@cards.post("/{card_id}/unarchive", response_model=CardOut)
def unarchive_card(card_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    card = svc.get_owned(db, Card, current.household.id, card_id)
    svc.unarchive_card(db, card)
    db.commit()
    return card


@cards.delete("/{card_id}", status_code=NO_CONTENT)
def delete_card(card_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    svc.delete_card(db, svc.get_owned(db, Card, current.household.id, card_id))
    db.commit()
    return _no_content()


# --- Categories --------------------------------------------------------------------

categories = APIRouter(prefix="/categories", tags=["categories"])


@categories.get("", response_model=Items[CategoryOut])
def list_categories(
    type: EntryType = Query(),  # noqa: A002 - matches the API's query parameter name
    include_archived: bool = False,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return Items(items=svc.list_categories(db, current.household.id, type, include_archived))


@categories.post("", status_code=status.HTTP_201_CREATED, response_model=CategoryOut)
def create_category(body: CategoryCreate, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    category = svc.create_category(db, current.household.id, body)
    db.commit()
    return category


@categories.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: uuid.UUID,
    body: CategoryPatch,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    category = svc.get_owned(db, Category, current.household.id, category_id)
    svc.update_category(db, category, body)
    db.commit()
    return category


@categories.post("/{category_id}/archive", response_model=CategoryOut)
def archive_category(category_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    category = svc.get_owned(db, Category, current.household.id, category_id)
    svc.set_active(db, category, False)
    db.commit()
    return category


@categories.post("/{category_id}/unarchive", response_model=CategoryOut)
def unarchive_category(category_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    category = svc.get_owned(db, Category, current.household.id, category_id)
    svc.set_active(db, category, True)
    db.commit()
    return category


@categories.delete("/{category_id}", status_code=NO_CONTENT)
def delete_category(category_id: uuid.UUID, current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    svc.delete_category(db, svc.get_owned(db, Category, current.household.id, category_id))
    db.commit()
    return _no_content()


router.include_router(accounts)
router.include_router(cards)
router.include_router(categories)
