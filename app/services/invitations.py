"""Invitations (specs/schemas.md §6)."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.errors import ApiError, validation_error
from app.core.security import hash_token, new_token
from app.domain.enums import InvitationStatus
from app.models import Invitation, User
from app.services.auth import normalize_email

INVITATION_TTL = timedelta(days=7)


def list_pending(db: Session, household_id: uuid.UUID, now: datetime) -> list[Invitation]:
    return list(
        db.scalars(
            select(Invitation)
            .where(
                Invitation.household_id == household_id,
                Invitation.status == InvitationStatus.PENDING,
                Invitation.expires_at > now,
            )
            .order_by(Invitation.created_at.desc())
        )
    )


def _expire_stale(db: Session, household_id: uuid.UUID, email: str, now: datetime) -> None:
    """Mark time-expired PENDING invitations as EXPIRED (§6.1 rule 4), so they no
    longer block a new invitation to the same email."""
    db.execute(
        update(Invitation)
        .where(
            Invitation.household_id == household_id,
            Invitation.email == email,
            Invitation.status == InvitationStatus.PENDING,
            Invitation.expires_at <= now,
        )
        .values(status=InvitationStatus.EXPIRED)
    )


def _reject_existing_account(db: Session, email: str) -> None:
    # v1: existing accounts can't be invited (§6.1 rule 6). Only members see this.
    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise validation_error({"email": ["This email already has an account"]})


def _new_invitation(
    db: Session, household_id: uuid.UUID, inviter: User, email: str, now: datetime
) -> tuple[Invitation, str]:
    token = new_token()
    invitation = Invitation(
        household_id=household_id,
        email=email,
        token_hash=hash_token(token),
        invited_by_id=inviter.id,
        status=InvitationStatus.PENDING,
        expires_at=now + INVITATION_TTL,
        created_at=now,
    )
    db.add(invitation)
    db.flush()
    return invitation, token


def create(db: Session, household_id: uuid.UUID, inviter: User, email: str, now: datetime) -> tuple[Invitation, str]:
    email = normalize_email(email)
    _reject_existing_account(db, email)
    _expire_stale(db, household_id, email, now)
    pending = db.scalar(
        select(Invitation.id).where(
            Invitation.household_id == household_id,
            Invitation.email == email,
            Invitation.status == InvitationStatus.PENDING,
        )
    )
    if pending is not None:
        raise ApiError(
            409, "CONFLICT", "An invitation to this email is already pending. Resend it instead.",
            fields={"email": ["An invitation to this email is already pending"]},
        )  # fmt: skip
    return _new_invitation(db, household_id, inviter, email, now)


def _get(db: Session, household_id: uuid.UUID, invitation_id: uuid.UUID) -> Invitation:
    invitation = db.get(Invitation, invitation_id)
    if invitation is None or invitation.household_id != household_id:
        raise ApiError(404, "NOT_FOUND", "Invitation not found.")
    return invitation


def resend(
    db: Session, household_id: uuid.UUID, actor: User, invitation_id: uuid.UUID, now: datetime
) -> tuple[Invitation, str]:
    """Revoke the invitation and issue a new one with a new token and expiry (§6.1 rule 3).
    Works for pending and expired invitations."""
    old = _get(db, household_id, invitation_id)
    if old.status in (InvitationStatus.ACCEPTED, InvitationStatus.REVOKED):
        raise ApiError(409, "CONFLICT", f"This invitation was already {old.status.value.lower()}.")
    _reject_existing_account(db, old.email)
    old.status = InvitationStatus.REVOKED
    db.flush()
    return _new_invitation(db, household_id, actor, old.email, now)


def revoke(db: Session, household_id: uuid.UUID, invitation_id: uuid.UUID) -> None:
    invitation = _get(db, household_id, invitation_id)
    if invitation.status is InvitationStatus.ACCEPTED:
        raise ApiError(409, "CONFLICT", "This invitation was already accepted.")
    if invitation.status is InvitationStatus.PENDING:
        invitation.status = InvitationStatus.REVOKED
        db.flush()
