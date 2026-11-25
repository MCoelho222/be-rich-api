"""Signup, sessions and passwords (specs/auth.md §4).

Services flush but never commit; routes own the transaction.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DbSession

from app.api.errors import ApiError, validation_error
from app.core.security import hash_password, hash_token, new_token, password_problems
from app.domain.enums import InvitationStatus, Language
from app.models import Household, Invitation, PasswordResetToken, Session, User
from app.services.households import create_household

SESSION_IDLE = timedelta(days=30)
SESSION_ABSOLUTE = timedelta(days=90)
SESSION_TOUCH_INTERVAL = timedelta(minutes=1)
RESET_TOKEN_TTL = timedelta(hours=1)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def check_password(password: str, *, email: str, name: str, field: str = "password") -> None:
    problems = password_problems(password, email=email, name=name)
    if problems:
        raise validation_error({field: problems})


# --- Invitations -------------------------------------------------------------------


def find_valid_invitation(db: DbSession, token: str, now: datetime) -> Invitation | None:
    invitation = db.scalar(select(Invitation).where(Invitation.token_hash == hash_token(token)))
    if invitation is None or invitation.status is not InvitationStatus.PENDING:
        return None
    if now >= invitation.expires_at:
        return None
    return invitation


def invitation_invalid() -> ApiError:
    return ApiError(410, "INVITATION_INVALID", "This invitation is no longer valid.")


# --- Signup ------------------------------------------------------------------------


def signup(
    db: DbSession,
    *,
    name: str,
    email: str,
    password: str,
    invitation_token: str | None,
    now: datetime,
    today: date,
    language: Language = Language.EN,
) -> User:
    """Create a user in a new household, or in the invitation's household (§4.1)."""
    email = normalize_email(email)
    check_password(password, email=email, name=name)

    invitation = None
    if invitation_token:
        invitation = find_valid_invitation(db, invitation_token, now)
        if invitation is None:
            raise invitation_invalid()
        if invitation.email != email:
            raise validation_error({"email": ["Must be the email address that was invited"]})

    if db.scalar(select(User.id).where(User.email == email)) is not None:
        raise email_taken()

    household_id = (
        invitation.household_id
        if invitation
        else create_household(db, person_name=name, today=today, language=language).id
    )
    user = User(
        household_id=household_id, name=name, email=email, password_hash=hash_password(password), language=language
    )
    db.add(user)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:  # concurrent signup with the same email
        raise email_taken() from exc

    if invitation:
        invitation.status = InvitationStatus.ACCEPTED
        invitation.accepted_at = now
    db.flush()
    return user


def email_taken() -> ApiError:
    return ApiError(409, "EMAIL_TAKEN", "Email already registered.", fields={"email": ["Email already registered"]})


# --- Sessions ----------------------------------------------------------------------


def create_session(db: DbSession, user: User, now: datetime, user_agent: str | None) -> str:
    """Create a session and return the raw token for the cookie."""
    token = new_token()
    db.add(
        Session(
            user_id=user.id,
            token_hash=hash_token(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + SESSION_IDLE,
            absolute_expires_at=now + SESSION_ABSOLUTE,
            user_agent=(user_agent or "")[:255] or None,
        )
    )
    db.flush()
    return token


def resolve_session(db: DbSession, token: str, now: datetime) -> Session | None:
    """The valid session for a token, sliding its idle expiry (at most once a minute)."""
    session = db.scalar(select(Session).where(Session.token_hash == hash_token(token)))
    if session is None or now >= session.expires_at or now >= session.absolute_expires_at:
        return None
    if now - session.last_seen_at >= SESSION_TOUCH_INTERVAL:
        session.last_seen_at = now
        session.expires_at = now + SESSION_IDLE
        db.flush()
    return session


def end_sessions(db: DbSession, user_id, *, except_session_id=None) -> None:
    stmt = delete(Session).where(Session.user_id == user_id)
    if except_session_id is not None:
        stmt = stmt.where(Session.id != except_session_id)
    db.execute(stmt)


# --- Passwords ---------------------------------------------------------------------


def create_reset_token(db: DbSession, user: User, now: datetime) -> str:
    """A new single-use reset token; earlier unused tokens stop working (§4.6)."""
    db.execute(
        delete(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)
        )
    )
    token = new_token()
    db.add(
        PasswordResetToken(
            user_id=user.id, token_hash=hash_token(token), expires_at=now + RESET_TOKEN_TTL, created_at=now
        )
    )
    db.flush()
    return token


def consume_reset_token(db: DbSession, token: str, now: datetime) -> PasswordResetToken:
    reset = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token)))
    if reset is None or reset.used_at is not None or now >= reset.expires_at:
        raise ApiError(410, "TOKEN_INVALID", "This link is no longer valid.")
    reset.used_at = now
    return reset


def set_password(user: User, password: str) -> None:
    check_password(password, email=user.email, name=user.name, field="new_password")
    user.password_hash = hash_password(password)


@dataclass(frozen=True)
class CurrentUser:
    user: User
    household: Household
    session: Session
