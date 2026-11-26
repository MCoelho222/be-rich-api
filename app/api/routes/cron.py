"""Scheduled jobs called by Vercel Cron (specs/operations.md §2.4)."""

import hmac
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.core.config import get_settings
from app.jobs.runner import DAILY_JOBS, run_job
from app.services.fx_provider import RateProvider, get_rate_provider

router = APIRouter(prefix="/cron", include_in_schema=False)


def get_cron_secret() -> str | None:
    return get_settings().cron_secret


def get_job_sessions() -> Callable[[], Session] | None:
    """None: each job opens its own session. Tests override it."""
    return None


def require_cron_secret(
    authorization: str | None = Header(None), secret: str | None = Depends(get_cron_secret)
) -> None:
    if not secret:
        raise ApiError(404, "NOT_FOUND", "Not Found")
    if authorization is None or not hmac.compare_digest(authorization.encode(), f"Bearer {secret}".encode()):
        raise ApiError(401, "UNAUTHENTICATED", "Invalid cron secret.")


@router.get("/daily", dependencies=[Depends(require_cron_secret)])
def daily(
    provider: RateProvider = Depends(get_rate_provider),
    sessions: Callable[[], Session] | None = Depends(get_job_sessions),
) -> JSONResponse:
    """Run the daily jobs. A failing job doesn't stop the others; any failure makes the
    response a 500, so it shows up as failed in Vercel's cron logs."""
    results = {
        name: run_job(name, session_factory=sessions, **({"provider": provider} if name == "fx_daily" else {}))
        for name in DAILY_JOBS
    }
    failed = [name for name, counts in results.items() if counts is None]
    return JSONResponse({"jobs": results, "failed": failed}, status_code=500 if failed else 200)
