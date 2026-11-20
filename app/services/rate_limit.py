"""Sliding-window rate limiting stored in Postgres (specs/auth.md §5)."""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import RateLimitHit


@dataclass(frozen=True)
class Limit:
    key: str
    max_hits: int
    window: timedelta


def retry_after(db: Session, limit: Limit, now: datetime) -> int | None:
    """Seconds until the next attempt is allowed, or None when under the limit."""
    since = now - limit.window
    count, oldest = db.execute(
        select(func.count(), func.min(RateLimitHit.created_at)).where(
            RateLimitHit.key == limit.key, RateLimitHit.created_at > since
        )
    ).one()
    if count < limit.max_hits:
        return None
    return max(1, math.ceil((oldest + limit.window - now).total_seconds()))


def first_exceeded(db: Session, limits: list[Limit], now: datetime) -> int | None:
    waits = [w for limit in limits if (w := retry_after(db, limit, now)) is not None]
    return max(waits) if waits else None


def record(db: Session, limits: list[Limit], now: datetime) -> None:
    db.add_all(RateLimitHit(key=limit.key, created_at=now) for limit in limits)
    db.flush()
