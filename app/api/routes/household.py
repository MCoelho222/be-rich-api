"""Household, members, invitations, profile and user lookup (specs/api.md §4-§6)."""

import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_now
from app.api.errors import ApiError
from app.api.routes.auth import me_body, rate_limited
from app.core.clock import today
from app.core.config import APP_TIMEZONE, get_settings
from app.db.session import get_db
from app.models import Household, Invitation, User
from app.schemas.auth import MeOut
from app.schemas.common import Items
from app.schemas.household import (
    HouseholdOut,
    HouseholdPatch,
    InvitationCreate,
    InvitationOut,
    MemberOut,
    ProfileOut,
    ProfilePatch,
    UserRefOut,
)
from app.services import invitations as invitation_service
from app.services import members as member_service
from app.services import profile as profile_service
from app.services.auth import CurrentUser
from app.services.email import EmailError, EmailSender, get_email_sender, invitation_email
from app.services.rate_limit import Limit, first_exceeded, record

router = APIRouter()

# --- Household ---------------------------------------------------------------------


@router.get("/household", response_model=HouseholdOut, tags=["household"])
def get_household(current: CurrentUser = Depends(get_current_user)) -> Household:
    return current.household


@router.patch("/household", response_model=HouseholdOut, tags=["household"])
def patch_household(
    body: HouseholdPatch,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Household:
    household = current.household
    sent = body.model_fields_set
    if "name" in sent:
        if body.name is None:
            raise ApiError(422, "VALIDATION_ERROR", "Some fields are invalid.", fields={"name": ["Can't be empty"]})
        household.name = body.name
    if "default_currency" in sent:
        if body.default_currency is None:
            raise ApiError(
                422, "VALIDATION_ERROR", "Some fields are invalid.", fields={"default_currency": ["Can't be empty"]}
            )
        household.default_currency = body.default_currency
    db.commit()
    return household


# --- Members -----------------------------------------------------------------------


@router.get("/household/members", response_model=Items[MemberOut], tags=["household"])
def list_members(current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> Items[MemberOut]:
    return Items(
        items=[
            MemberOut(id=u.id, name=u.name, email=u.email, is_you=u.id == current.user.id)
            for u in member_service.members(db, current.household.id)
        ]
    )


@router.delete("/household/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["household"])
def remove_member(
    user_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    member_service.remove(db, current.household.id, current.user, user_id, today())
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/household/leave", response_model=MeOut, tags=["household"])
def leave_household(current: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)) -> MeOut:
    new_household = member_service.leave(db, current.user, today())
    db.commit()
    return me_body(current.user, new_household)


@router.get("/users/{user_id}", response_model=UserRefOut, tags=["household"])
def get_user_ref(
    user_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserRefOut:
    found = member_service.visible_user(db, current.household.id, user_id)
    if found is None:
        raise ApiError(404, "NOT_FOUND", "User not found.")
    user, is_current = found
    return UserRefOut(id=user.id, name=user.name, is_current_member=is_current)


# --- Profile -----------------------------------------------------------------------


@router.get("/me", response_model=ProfileOut, tags=["profile"])
def get_profile(current: CurrentUser = Depends(get_current_user)) -> ProfileOut:
    return profile_service.to_out(current.user)


@router.patch("/me", response_model=ProfileOut, tags=["profile"])
def patch_profile(
    body: ProfilePatch,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfileOut:
    profile_service.update_profile(db, current.user, body, today())
    db.commit()
    db.refresh(current.user)
    return profile_service.to_out(current.user)


# --- Invitations -------------------------------------------------------------------

INVITES_PER_DAY = 20


def _invite_limit(household_id: uuid.UUID) -> list[Limit]:
    return [Limit(f"invite:household:{household_id}", INVITES_PER_DAY, timedelta(days=1))]


def _send_invitation(
    sender: EmailSender, invitation: Invitation, token: str, inviter: User, household: Household
) -> None:
    """Sent after commit. A failure is reported as 502 so the UI can offer "Resend"."""
    link = f"{get_settings().app_url}/invite/{token}"
    expires_on = invitation.expires_at.astimezone(APP_TIMEZONE).strftime("%d/%m/%Y")
    try:
        sender.send(invitation_email(invitation.email, inviter.name, household.name, expires_on, link))
    except EmailError as exc:
        raise ApiError(502, "EMAIL_FAILED", "The invitation was saved but the email could not be sent.") from exc


@router.get("/invitations", response_model=Items[InvitationOut], tags=["invitations"])
def list_invitations(
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
) -> Items[InvitationOut]:
    pending = invitation_service.list_pending(db, current.household.id, now)
    return Items(items=[InvitationOut.model_validate(i) for i in pending])


@router.post("/invitations", status_code=status.HTTP_201_CREATED, response_model=InvitationOut, tags=["invitations"])
def create_invitation(
    body: InvitationCreate,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
    sender: EmailSender = Depends(get_email_sender),
) -> Invitation:
    limits = _invite_limit(current.household.id)
    if (wait := first_exceeded(db, limits, now)) is not None:
        raise rate_limited(wait)
    invitation, token = invitation_service.create(db, current.household.id, current.user, str(body.email), now)
    record(db, limits, now)
    db.commit()
    _send_invitation(sender, invitation, token, current.user, current.household)
    return invitation


@router.post(
    "/invitations/{invitation_id}/resend",
    status_code=status.HTTP_201_CREATED,
    response_model=InvitationOut,
    tags=["invitations"],
)
def resend_invitation(
    invitation_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    now: datetime = Depends(get_now),
    sender: EmailSender = Depends(get_email_sender),
) -> Invitation:
    limits = _invite_limit(current.household.id)
    if (wait := first_exceeded(db, limits, now)) is not None:
        raise rate_limited(wait)
    invitation, token = invitation_service.resend(db, current.household.id, current.user, invitation_id, now)
    record(db, limits, now)
    db.commit()
    _send_invitation(sender, invitation, token, current.user, current.household)
    return invitation


@router.post("/invitations/{invitation_id}/revoke", status_code=status.HTTP_204_NO_CONTENT, tags=["invitations"])
def revoke_invitation(
    invitation_id: uuid.UUID,
    current: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    invitation_service.revoke(db, current.household.id, invitation_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
