"""Job registry, run logging and the APScheduler schedule (specs/operations.md §2.2)."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.core.clock import utcnow
from app.core.config import APP_TIMEZONE
from app.db.session import SessionLocal, get_engine
from app.jobs import tasks
from app.services.fx_provider import get_rate_provider

logger = logging.getLogger("app.jobs")


@dataclass(frozen=True)
class Job:
    name: str
    func: Callable[..., dict[str, int]]
    trigger: CronTrigger
    run_at_startup: bool = False
    needs_provider: bool = False


def _cron(**fields: Any) -> CronTrigger:
    return CronTrigger(timezone=APP_TIMEZONE, **fields)


JOBS: dict[str, Job] = {
    job.name: job
    for job in (
        # 13:00, retried hourly until 20:00 (a successful run makes the rest no-ops)
        Job("fx_daily", tasks.fx_daily, _cron(hour="13-20", minute=0), needs_provider=True),
        Job("holidays_seed", tasks.holidays_seed, _cron(month=1, day=2, hour=3, minute=0), run_at_startup=True),
        Job("invitations_expire", tasks.invitations_expire, _cron(minute=0)),
        Job("sessions_cleanup", tasks.sessions_cleanup, _cron(hour=4, minute=0)),
        Job("rate_limit_cleanup", tasks.rate_limit_cleanup, _cron(hour=4, minute=10)),
    )
}


# Where no worker runs the scheduler (Vercel), one daily call runs these in order
# (specs/operations.md §2.4). All are idempotent, so running them daily is safe.
DAILY_JOBS = ("fx_daily", "invitations_expire", "sessions_cleanup", "rate_limit_cleanup", "holidays_seed")


def run_job(name: str, session_factory: Callable[[], Session] | None = None, **deps: Any) -> dict[str, int] | None:
    """Run one job in its own transaction, logging start, end, counts and errors.

    Returns the job's counts, or None if it failed (the error is logged, not raised,
    so one failing job never stops the scheduler).
    """
    job = JOBS[name]
    if job.needs_provider and "provider" not in deps:
        deps["provider"] = get_rate_provider()
    if session_factory is None:
        get_engine()
        session_factory = SessionLocal
    started = time.monotonic()
    logger.info("job %s started", name)
    with session_factory() as db:
        try:
            counts = job.func(db, utcnow(), **deps)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("job %s failed after %.2fs", name, time.monotonic() - started)
            return None
    logger.info("job %s finished in %.2fs: %s", name, time.monotonic() - started, counts)
    return counts


def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone=APP_TIMEZONE)
    for job in JOBS.values():
        # coalesce + max_instances=1: a late or slow run never piles up duplicates
        scheduler.add_job(run_job, job.trigger, args=[job.name], id=job.name, coalesce=True,
                          max_instances=1, misfire_grace_time=600)  # fmt: skip
    return scheduler


def serve() -> None:
    for job in JOBS.values():
        if job.run_at_startup:
            run_job(job.name)
    scheduler = build_scheduler()
    logger.info("scheduler started with jobs: %s", ", ".join(JOBS))
    scheduler.start()
