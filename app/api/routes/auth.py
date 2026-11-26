"""/auth endpoints and the public invitation lookup (specs/auth.md §4)."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.api.deps import (
    SESSION_COOKIE,
    check_csrf,
    clear_auth_cookies,
    client_ip,
    get_current,
    get_current_user,
    get_now,
    set_auth_cookies,
)
from app.api.errors import ApiError
from app.core.clock import today
from app.core.config import APP_TIMEZONE, get_settings
from app.core.security import burn_password_check, hash_password, needs_rehash, verify_password
from app.db.session import get_db
from app.models import Household, User
from app.schemas.auth import (
    ChangePasswordIn,
    InvitationLookupOut,
    LoginIn,
    MeOut,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    SignupIn,
)
from app.services import auth as auth_service
from app.services.auth import CurrentUser, normalize_email
from app.services.email import (
    EmailSender,
    get_email_sender,
    password_changed_email,
    password_reset_email,
    send_quietly,
)
from app.services.rate_limit import Limit, first_exceeded, record

router = APIRouter(tags=["auth"])

MINUTES_15, HOUR = timedelta(minutes=15), timedelta(hours=1)


def me_body(user: User, household: Household) -> MeOut:
    return MeOut.model_validate(
        {
            "user": {"id": user.id, "name": user.name, "email": user.email, "household_id": user.household_id,
                     "language": user.language, "avatar": user.avatar},
            "household": {
                "id": household.id,
                "name": household.name,
                "default_currency": household.default_currency,
            },
        }
    )


def rate_limited(seconds: int) -> ApiError:
    return ApiError(
        429, "RATE_LIMITED", "Too many attempts. Try again later.", headers={"Retry-After": str(seconds)}
    )


def local_time(now: datetime) -> str:
    return now.astimezone(APP_TIMEZONE).strftime("%d/%m/%Y %H:%M")


@router.post("/auth/signup", status_code=status.HTTP_201_CREATED, response_model=MeOut)
def signup(
    body: SignupIn,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
    now: datetime = Depends(get_now),
) -> MeOut:
    limits = [Limit(f"signup:ip:{client_ip(request)}", 10, HOUR)]
    if (wait := first_exceeded(db, limits, now)) is not None:
        raise rate_limited(wait)
    record(db, limits, now)
    db.commit()  # count the attempt even if the signup fails below

    user = auth_service.signup(
        db,
        name=body.name,
        email=str(body.email),
        password=body.password,
        invitation_token=body.invitation_token,
        now=now,
        today=today(),
        language=body.language,
    )
    token = auth_service.create_session(db, user, now, request.headers.get("user-agent"))
    db.commit()
    set_auth_cookies(response, token)
    return me_body(user, db.get(Household, user.household_id))


@router.post("/auth/login", response_model=MeOut)
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
    now: datetime = Depends(get_now),
) -> MeOut:
    email = normalize_email(body.email)
    limits = [
        Limit(f"login:email:{email}", 5, MINUTES_15),
        Limit(f"login:ip:{client_ip(request)}", 20, MINUTES_15),
    ]
    if (wait := first_exceeded(db, limits, now)) is not None:
        raise rate_limited(wait)

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        burn_password_check(body.password)
        valid = False
    else:
        valid = verify_password(user.password_hash, body.password)
    if not valid:
        record(db, limits, now)  # only failures count
        db.commit()
        raise ApiError(401, "INVALID_CREDENTIALS", "Invalid email or password.")

    assert user is not None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    token = auth_service.create_session(db, user, now, request.headers.get("user-agent"))
    db.commit()
    set_auth_cookies(response, token)
    return me_body(user, db.get(Household, user.household_id))


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    db: DbSession = Depends(get_db),
    now: datetime = Depends(get_now),
) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    session = auth_service.resolve_session(db, token, now) if token else None
    if session is not None:
        check_csrf(request)
        db.delete(session)
        db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    clear_auth_cookies(response)
    return response


@router.get("/auth/me", response_model=MeOut)
def me(current: CurrentUser = Depends(get_current)) -> MeOut:
    return me_body(current.user, current.household)


@router.post("/auth/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: ChangePasswordIn,
    current: CurrentUser = Depends(get_current_user),
    db: DbSession = Depends(get_db),
    now: datetime = Depends(get_now),
    email_sender: EmailSender = Depends(get_email_sender),
) -> Response:
    user = current.user
    if not verify_password(user.password_hash, body.current_password):
        raise ApiError(401, "INVALID_CREDENTIALS", "Current password is incorrect.")
    auth_service.set_password(user, body.new_password)
    auth_service.end_sessions(db, user.id, except_session_id=current.session.id)
    db.commit()
    send_quietly(email_sender, password_changed_email(user.email, user.name, local_time(now)))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/auth/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
def request_password_reset(
    body: PasswordResetRequestIn,
    request: Request,
    db: DbSession = Depends(get_db),
    now: datetime = Depends(get_now),
    email_sender: EmailSender = Depends(get_email_sender),
) -> Response:
    """Always 202, so the response never reveals whether the email exists."""
    accepted = Response(status_code=status.HTTP_202_ACCEPTED)
    email = normalize_email(body.email)
    limits = [
        Limit(f"reset:email:{email}", 3, HOUR),
        Limit(f"reset:ip:{client_ip(request)}", 10, HOUR),
    ]
    if first_exceeded(db, limits, now) is not None:
        return accepted  # silently dropped
    record(db, limits, now)

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        db.commit()
        return accepted
    token = auth_service.create_reset_token(db, user, now)
    db.commit()
    link = f"{get_settings().app_url}/reset-password/{token}"
    send_quietly(email_sender, password_reset_email(user.email, user.name, link))
    return accepted


@router.post("/auth/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
def confirm_password_reset(
    body: PasswordResetConfirmIn,
    db: DbSession = Depends(get_db),
    now: datetime = Depends(get_now),
    email_sender: EmailSender = Depends(get_email_sender),
) -> Response:
    reset = auth_service.consume_reset_token(db, body.token, now)
    user = db.get(User, reset.user_id)
    assert user is not None
    auth_service.set_password(user, body.new_password)
    auth_service.end_sessions(db, user.id)
    db.commit()
    send_quietly(email_sender, password_changed_email(user.email, user.name, local_time(now)))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/invitations/lookup", response_model=InvitationLookupOut)
def lookup_invitation(
    token: str = Query(max_length=200),
    db: DbSession = Depends(get_db),
    now: datetime = Depends(get_now),
) -> InvitationLookupOut:
    invitation = auth_service.find_valid_invitation(db, token, now)
    if invitation is None:
        raise auth_service.invitation_invalid()
    household = db.get(Household, invitation.household_id)
    inviter = db.get(User, invitation.invited_by_id)
    assert household is not None and inviter is not None
    return InvitationLookupOut(household_name=household.name, email=invitation.email, invited_by_name=inviter.name)
