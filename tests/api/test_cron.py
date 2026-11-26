"""The Vercel Cron endpoint (specs/operations.md §2.4)."""

import contextlib

import pytest
from sqlalchemy import func, select

from app.api.routes import cron
from app.jobs.runner import DAILY_JOBS
from app.models import ExchangeRate, Holiday
from app.services.fx_provider import get_rate_provider
from tests.jobs.test_jobs import FakeProvider

SECRET = "s3cret-for-tests"
AUTH = {"Authorization": f"Bearer {SECRET}"}


@pytest.fixture
def provider(app, db):
    fake = FakeProvider()
    app.dependency_overrides[get_rate_provider] = lambda: fake
    app.dependency_overrides[cron.get_job_sessions] = lambda: (lambda: contextlib.nullcontext(db))
    app.dependency_overrides[cron.get_cron_secret] = lambda: SECRET
    return fake


def count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def test_disabled_without_a_secret(client, app):
    app.dependency_overrides[cron.get_cron_secret] = lambda: None
    assert client.get("cron/daily", headers=AUTH).status_code == 404


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": SECRET}])
def test_rejects_a_wrong_secret(client, provider, headers):
    assert client.get("cron/daily", headers=headers).status_code == 401
    assert provider.calls == []


def test_runs_every_daily_job(client, db, provider):
    response = client.get("cron/daily", headers=AUTH)
    assert response.status_code == 200, response.json()
    body = response.json()
    assert list(body["jobs"]) == list(DAILY_JOBS) and body["failed"] == []
    assert body["jobs"]["fx_daily"]["stored"] == 6  # every pair of BRL, USD and EUR
    assert count(db, ExchangeRate) == 6 and count(db, Holiday) > 0


def test_a_failing_job_doesnt_stop_the_others(client, db, provider):
    provider.fail = True
    response = client.get("cron/daily", headers=AUTH)
    assert response.status_code == 500
    assert response.json()["failed"] == ["fx_daily"]
    assert count(db, Holiday) > 0  # holidays_seed still ran
