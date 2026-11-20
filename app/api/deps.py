"""Request dependencies: authentication, CSRF and cookies (specs/auth.md §1, §3)."""

from datetime import datetime

from fastapi import Depends, Request, Response
from sqlalchemy.orm import Session as DbSession

from app.api.errors import ApiError
from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.security import new_token, tokens_match
from app.db.session import get_db
from app.models import Household, User
from app.services.auth import SESSION_ABSOLUTE, CurrentUser, resolve_session

SESSION_COOKIE = "brs_session"
CSRF_COOKIE = "brs_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def client_ip(request: Request) -> str:
    # Behind Caddy, uvicorn/gunicorn must run with proxy headers enabled so this
    # is the real client address (specs/operations.md §1).
    return request.client.host if request.client else "unknown"


def set_auth_cookies(response: Response, session_token: str) -> None:
    """Set the session cookie and rotate the CSRF cookie (at login and signup)."""
    secure = get_settings().cookie_secure
    max_age = int(SESSION_ABSOLUTE.total_seconds())
    response.set_cookie(
        SESSION_COOKIE, session_token, max_age=max_age, httponly=True, secure=secure, samesite="lax", path="/"
    )
    response.set_cookie(
        CSRF_COOKIE, new_token(), max_age=max_age, httponly=False, secure=secure, samesite="lax", path="/"
    )


def clear_auth_cookies(response: Response) -> None:
    secure = get_settings().cookie_secure
    for name, httponly in ((SESSION_COOKIE, True), (CSRF_COOKIE, False)):
        response.delete_cookie(name, path="/", secure=secure, httponly=httponly, samesite="lax")


def check_csrf(request: Request) -> None:
    """Mutating requests must echo the CSRF cookie in the X-CSRF-Token header."""
    if request.method in SAFE_METHODS:
        return
    header = request.headers.get(CSRF_HEADER)
    cookie = request.cookies.get(CSRF_COOKIE)
    if not header or not cookie or not tokens_match(header, cookie):
        raise ApiError(403, "CSRF_FAILED", "Missing or invalid CSRF token.")


def unauthenticated() -> ApiError:
    return ApiError(401, "UNAUTHENTICATED", "You need to log in.")


def get_now() -> datetime:
    return utcnow()


def get_current(
    request: Request, db: DbSession = Depends(get_db), now: datetime = Depends(get_now)
) -> CurrentUser:
    """The logged-in user and their *current* household, resolved on every request."""
    token = request.cookies.get(SESSION_COOKIE)
    session = resolve_session(db, token, now) if token else None
    if session is None:
        raise unauthenticated()
    user = db.get(User, session.user_id)
    if user is None:
        raise unauthenticated()
    household = db.get(Household, user.household_id)
    assert household is not None
    db.commit()  # persist the sliding expiry, if it moved
    return CurrentUser(user=user, household=household, session=session)


def get_current_user(request: Request, current: CurrentUser = Depends(get_current)) -> CurrentUser:
    """Authenticated + CSRF-checked: use on every household route."""
    check_csrf(request)
    return current
