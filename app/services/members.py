"""Membership: listing, leaving and removing members (specs/schemas.md §4.2)."""

import uuid
from datetime import date

from sqlalchemy import exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.models import Card, Expense, Household, Income, Invitation, Recurrence, User
from app.services.auth import end_sessions
from app.services.households import create_household


def members(db: Session, household_id: uuid.UUID) -> list[User]:
    return list(db.scalars(select(User).where(User.household_id == household_id).order_by(User.name)))


def _lock_household(db: Session, household_id: uuid.UUID) -> None:
    """Serialize membership changes, so two members can't remove each other at once
    and leave the household empty."""
    db.execute(select(Household.id).where(Household.id == household_id).with_for_update())


def _member_count(db: Session, household_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(User).where(User.household_id == household_id))


def last_member() -> ApiError:
    return ApiError(409, "LAST_MEMBER", "The last member of a household can't leave or be removed.")


def _move_out(db: Session, user: User, today: date) -> Household:
    """Move `user` to a new, empty household of their own (§4.2 rules 3-5).

    All data stays behind; cards they own are archived.
    """
    db.execute(
        update(Card)
        .where(Card.household_id == user.household_id, Card.owner_id == user.id)
        .values(is_active=False)
    )
    household = create_household(db, person_name=user.name, today=today, language=user.language)
    user.household_id = household.id
    db.flush()
    return household


def leave(db: Session, user: User, today: date) -> Household:
    _lock_household(db, user.household_id)
    if _member_count(db, user.household_id) <= 1:
        raise last_member()
    return _move_out(db, user, today)


def remove(db: Session, household_id: uuid.UUID, actor: User, target_id: uuid.UUID, today: date) -> None:
    if target_id == actor.id:
        raise ApiError(422, "VALIDATION_ERROR", "To leave the household, use /household/leave.")
    _lock_household(db, household_id)
    target = db.get(User, target_id)
    if target is None or target.household_id != household_id:
        raise ApiError(404, "NOT_FOUND", "Member not found.")
    if _member_count(db, household_id) <= 1:
        raise last_member()
    _move_out(db, target, today)
    end_sessions(db, target.id)  # access ends immediately (§4.2 rule 3)


def visible_user(db: Session, household_id: uuid.UUID, user_id: uuid.UUID) -> tuple[User, bool] | None:
    """A user the caller may see: a current member, or a former member that this
    household's data still references (§4.2 rule 4). Returns (user, is_current)."""
    user = db.get(User, user_id)
    if user is None:
        return None
    if user.household_id == household_id:
        return user, True
    references = [
        select(Expense.id).where(
            Expense.household_id == household_id,
            or_(Expense.spender_id == user_id, Expense.created_by_id == user_id),
        ),
        select(Income.id).where(
            Income.household_id == household_id,
            or_(Income.receiver_id == user_id, Income.created_by_id == user_id),
        ),
        select(Recurrence.id).where(
            Recurrence.household_id == household_id,
            or_(Recurrence.person_id == user_id, Recurrence.created_by_id == user_id),
        ),
        select(Card.id).where(Card.household_id == household_id, Card.owner_id == user_id),
        select(Invitation.id).where(Invitation.household_id == household_id, Invitation.invited_by_id == user_id),
    ]
    if any(db.scalar(select(exists(ref))) for ref in references):
        return user, False
    return None
