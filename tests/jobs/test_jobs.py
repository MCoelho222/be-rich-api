"""Scheduled jobs and the exchange-rate provider (specs/operations.md §2)."""

import contextlib
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select

from app.core.security import hash_token
from app.domain.enums import Currency, InvitationStatus
from app.jobs import tasks
from app.jobs.__main__ import main
from app.jobs.runner import JOBS, build_scheduler, run_job
from app.models import ExchangeRate, Holiday, Invitation, PasswordResetToken, RateLimitHit, Session as AuthSession
from app.services.fx import historical_rate
from app.services.fx_provider import FrankfurterProvider, Quote, RateProviderError
from tests.db.factories import make_household, make_user

NOW = datetime(2026, 11, 20, 16, 0, tzinfo=timezone.utc)  # 13:00 in São Paulo


def count(db, model, *where) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where))


class FakeProvider:
    source = "fake"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple] = []

    def latest(self, base, quotes):
        return self._quotes(date(2026, 11, 19), base, quotes)

    def on(self, day, base, quotes):
        return self._quotes(day, base, quotes)

    def _quotes(self, day, base, quotes):
        self.calls.append((day, base, tuple(quotes)))
        if self.fail:
            raise RateProviderError("provider down")
        return [Quote(day, base, q, Decimal("2.5")) for q in quotes]


class TestFxDaily:
    def test_stores_every_pair_then_skips_for_the_day(self, db):
        provider = FakeProvider()
        assert tasks.fx_daily(db, NOW, provider) == {"skipped": 0, "stored": 6}
        assert count(db, ExchangeRate) == 6
        assert tasks.fx_daily(db, NOW + timedelta(hours=1), provider) == {"skipped": 1, "stored": 0}
        assert len(provider.calls) == 3

    def test_is_idempotent_for_the_same_rate_date(self, db):
        tasks.fx_daily(db, NOW, FakeProvider())
        tasks.fx_daily(db, NOW + timedelta(days=1), FakeProvider())  # provider still returns the 19th
        assert count(db, ExchangeRate) == 6

    def test_a_single_historical_pair_does_not_count_as_done(self, db):
        historical_rate(db, FakeProvider(), Currency.USD, Currency.BRL, date(2026, 10, 1), NOW)
        assert tasks.fx_daily(db, NOW, FakeProvider())["skipped"] == 0

    def test_failure_is_logged_and_rolled_back(self, db, caplog):
        with db.begin_nested():  # stand-in for the runner's own transaction
            result = run_job("fx_daily", session_factory=lambda: contextlib.nullcontext(db), provider=FakeProvider(fail=True))
        assert result is None
        assert "job fx_daily failed" in caplog.text
        assert count(db, ExchangeRate) == 0


class TestHistoricalRate:
    def test_cache_hit_within_a_few_days(self, db):
        tasks.fx_daily(db, NOW, FakeProvider())  # rate on 2026-11-19
        provider = FakeProvider()
        # Sunday the 22nd: Thursday's rate is close enough, no fetch
        assert historical_rate(db, provider, Currency.USD, Currency.BRL, date(2026, 11, 22), NOW) == (
            Decimal("2.5"), date(2026, 11, 19),
        )  # fmt: skip
        assert provider.calls == []

    def test_cache_miss_fetches_and_stores(self, db):
        provider = FakeProvider()
        rate, on = historical_rate(db, provider, Currency.USD, Currency.BRL, date(2026, 3, 2), NOW)
        assert (rate, on) == (Decimal("2.5"), date(2026, 3, 2))
        assert provider.calls == [(date(2026, 3, 2), Currency.USD, (Currency.BRL,))]
        assert count(db, ExchangeRate, ExchangeRate.rate_date == date(2026, 3, 2)) == 1

    def test_provider_failure_falls_back_to_older_cache_or_none(self, db):
        failing = FakeProvider(fail=True)
        assert historical_rate(db, failing, Currency.USD, Currency.BRL, date(2026, 3, 2), NOW) is None
        tasks.fx_daily(db, NOW, FakeProvider())
        assert historical_rate(db, failing, Currency.USD, Currency.BRL, date(2026, 12, 31), NOW) == (
            Decimal("2.5"), date(2026, 11, 19),
        )  # fmt: skip

    def test_same_currency(self, db):
        assert historical_rate(db, FakeProvider(fail=True), Currency.BRL, Currency.BRL, date(2026, 1, 1), NOW)[0] == 1


class TestHousekeeping:
    def test_holidays_seed_covers_three_years_and_never_deletes(self, db):
        db.add(Holiday(date=date(2026, 3, 19), name="Custom local holiday"))
        db.flush()
        first = tasks.holidays_seed(db, NOW)
        assert first["inserted"] == 39  # 13 national bank holidays x 2026-2028
        assert tasks.holidays_seed(db, NOW) == {"inserted": 0}
        assert db.get(Holiday, date(2026, 3, 19)) is not None
        assert db.get(Holiday, date(2028, 11, 20)) is not None

    def test_invitations_expire(self, db):
        household = make_household(db)
        user = make_user(db, household)
        for email, expires in (("old@example.com", NOW - timedelta(seconds=1)), ("new@example.com", NOW + timedelta(days=1))):
            db.add(Invitation(household_id=household.id, email=email, token_hash=hash_token(email),
                              invited_by_id=user.id, expires_at=expires))  # fmt: skip
        db.flush()
        assert tasks.invitations_expire(db, NOW) == {"expired": 1}
        assert count(db, Invitation, Invitation.status == InvitationStatus.PENDING) == 1

    def test_sessions_cleanup(self, db):
        household = make_household(db)
        user = make_user(db, household)

        def session(token, expires, absolute):
            db.add(AuthSession(user_id=user.id, token_hash=hash_token(token), last_seen_at=NOW,
                               expires_at=expires, absolute_expires_at=absolute))  # fmt: skip

        session("valid", NOW + timedelta(days=1), NOW + timedelta(days=60))
        session("idle", NOW - timedelta(seconds=1), NOW + timedelta(days=60))
        session("absolute", NOW + timedelta(days=1), NOW - timedelta(seconds=1))
        for token, expires, used in (
            ("fresh", NOW + timedelta(minutes=30), None),
            ("used", NOW + timedelta(minutes=30), NOW),
            ("recently-expired", NOW - timedelta(hours=2), None),
            ("long-expired", NOW - timedelta(days=2), None),
        ):
            db.add(PasswordResetToken(user_id=user.id, token_hash=hash_token(token), expires_at=expires, used_at=used))
        db.flush()
        assert tasks.sessions_cleanup(db, NOW) == {"sessions": 2, "reset_tokens": 2}

    def test_rate_limit_cleanup(self, db):
        db.add_all([RateLimitHit(key="k", created_at=NOW - timedelta(days=2)), RateLimitHit(key="k", created_at=NOW)])
        db.flush()
        assert tasks.rate_limit_cleanup(db, NOW) == {"deleted": 1}


class TestFrankfurter:
    def provider(self, handler):
        return FrankfurterProvider("https://fx.test/v1", transport=httpx.MockTransport(handler))

    def test_parses_rates_and_ignores_unsupported_codes(self):
        def handler(request):
            assert request.url.path == "/v1/latest"
            assert dict(request.url.params) == {"base": "USD", "symbols": "BRL,EUR"}
            return httpx.Response(200, json={"amount": 1.0, "base": "USD", "date": "2026-11-20",
                                             "rates": {"BRL": 5.938, "EUR": 0.90992, "JPY": 150.1}})  # fmt: skip

        quotes = self.provider(handler).latest(Currency.USD, [Currency.BRL, Currency.EUR])
        assert quotes == [
            Quote(date(2026, 11, 20), Currency.USD, Currency.BRL, Decimal("5.938")),
            Quote(date(2026, 11, 20), Currency.USD, Currency.EUR, Decimal("0.90992")),
        ]

    def test_historical_path(self):
        seen = []

        def handler(request):
            seen.append(request.url.path)
            return httpx.Response(200, json={"base": "USD", "date": "2026-11-13", "rates": {"BRL": 5.6637}})

        self.provider(handler).on(date(2026, 11, 15), Currency.USD, [Currency.BRL])
        assert seen == ["/v1/2026-11-15"]

    @pytest.mark.parametrize(
        "response", [httpx.Response(500), httpx.Response(200, text="not json"), httpx.Response(200, json={"rates": {}})]
    )
    def test_errors_become_provider_errors(self, response):
        with pytest.raises(RateProviderError):
            self.provider(lambda request: response).latest(Currency.USD, [Currency.BRL])


class TestScheduler:
    def test_schedule_matches_operations_spec(self):
        scheduler = build_scheduler()
        triggers = {job.id: str(job.trigger) for job in scheduler.get_jobs()}
        assert set(triggers) == set(JOBS)
        assert "hour='13-20', minute='0'" in triggers["fx_daily"]
        assert "month='1', day='2', hour='3', minute='0'" in triggers["holidays_seed"]
        assert "hour='4', minute='10'" in triggers["rate_limit_cleanup"]
        assert all("America/Sao_Paulo" in str(job.trigger.timezone) for job in scheduler.get_jobs())

    def test_cli(self, monkeypatch, capsys):
        assert main(["list"]) == 0
        assert "fx_daily" in capsys.readouterr().out
        ran = []
        monkeypatch.setattr("app.jobs.__main__.run_job", lambda name: ran.append(name) or {"ok": 1})
        assert main(["run", "holidays_seed"]) == 0
        assert ran == ["holidays_seed"]
        monkeypatch.setattr("app.jobs.__main__.run_job", lambda name: None)
        assert main(["run", "fx_daily"]) == 1
