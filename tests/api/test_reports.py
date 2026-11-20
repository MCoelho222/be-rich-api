"""Read models (specs/api.md §13).

One household, seen on 2026-11-20:
- Nubank opens with 1000.00 on 2026-10-31.
- Salary 5000.00 received by PIX on Nov 5; groceries 200.00 paid by PIX on Nov 10.
- Headphones 300.00 on the credit card on Nov 15, in 3 installments. The card closes
  on the 25th and is due on the 5th: 100.00 each on Dec 7 (Dec 5 is a Saturday),
  Jan 5 and Feb 5.
- Rent 1800.00 by PIX on the 25th since September. Sep and Oct were never registered,
  so they are overdue and left out of projections.
- Gym 100.00 on the credit card on the 1st from December: the first one is due Jan 5.
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.api.routes import recurrences as recurrence_routes
from app.api.routes import reports as report_routes
from app.domain.enums import Currency
from app.models import ExchangeRate
from app.services.fx_provider import RateProviderError, get_rate_provider
from tests.api.conftest import csrf, signup

TODAY = date(2026, 11, 20)


class OfflineProvider:
    source = "test"

    def latest(self, base, quotes):
        raise RateProviderError("offline")

    def on(self, day, base, quotes):
        raise RateProviderError("offline")


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch, app):
    monkeypatch.setattr(recurrence_routes, "today", lambda: TODAY)
    monkeypatch.setattr(report_routes, "today", lambda: TODAY)
    app.dependency_overrides[get_rate_provider] = OfflineProvider


def post(client, path, json):
    response = client.post(path, json=json, headers=csrf(client))
    assert response.status_code == 201, response.json()
    return response.json()


@pytest.fixture
def h(client):
    owner = signup(client).json()
    bank = post(client, "accounts", {"name": "Nubank", "opening_balance": "1000.00", "opening_balance_date": "2026-10-31"})
    card = post(client, "cards", {"alias": "NuCredit", "account_id": bank["id"], "best_buy_day": 25, "due_day": 5})
    cats = {c["name"]: c["id"] for c in client.get("categories", params={"type": "EXPENSE"}).json()["items"]}
    salary = post(client, "categories", {"type": "INCOME", "name": "Salary"})["id"]

    post(client, "incomes", {"transaction_date": "2026-11-05", "category_id": salary, "total_amount": "5000.00",
                             "parts": [{"payment_method": "PIX", "account_id": bank["id"]}]})  # fmt: skip
    post(client, "expenses", {"transaction_date": "2026-11-10", "category_id": cats["Food"], "total_amount": "200.00",
                              "description": "Groceries",
                              "parts": [{"payment_method": "PIX", "account_id": bank["id"]}]})  # fmt: skip
    post(client, "expenses", {"transaction_date": "2026-11-15", "category_id": cats["Entertainment"],
                              "total_amount": "300.00", "description": "Headphones",
                              "parts": [{"payment_method": "CREDIT", "card_id": card["id"], "installments": 3}]})  # fmt: skip
    post(client, "recurrences", {"type": "EXPENSE", "amount": "1800.00", "payment_method": "PIX",
                                 "account_id": bank["id"], "category_id": cats["Rent"], "start_date": "2026-09-25",
                                 "description": "Rent"})  # fmt: skip
    post(client, "recurrences", {"type": "EXPENSE", "amount": "100.00", "payment_method": "CREDIT",
                                 "card_id": card["id"], "category_id": cats["Gym"], "start_date": "2026-12-01",
                                 "description": "Gym"})  # fmt: skip
    return {"owner": owner["user"]["id"], "bank": bank["id"], "card": card["id"], "cats": cats, "salary": salary}


def get(client, path, **params):
    response = client.get(path, params=params)
    assert response.status_code == 200, response.json()
    return response.json()


NOV = {"from": "2026-11-01", "to": "2026-11-30"}


class TestBalances:
    def test_today(self, client, h):
        body = get(client, "balances", account_id=h["bank"])
        assert (body["date"], body["projected"], body["total"], body["currency"]) == ("2026-11-20", False, "5800.00", "BRL")
        assert body["accounts"] == [{"account_id": h["bank"], "account_currency": "BRL", "balance": "5800.00", "converted": "5800.00"}]
        assert body["unconverted"] == [] and body["rates_as_of"] is None

    def test_projected(self, client, h):
        # 5800 - rent Nov 25 - installment Dec 7 - rent Dec 25
        body = get(client, "balances", date="2026-12-31", account_id=h["bank"])
        assert (body["projected"], body["total"]) == (True, "2100.00")

    def test_before_opening_is_null(self, client, h):
        body = get(client, "balances", date="2026-10-01", account_id=h["bank"])
        assert body["accounts"][0]["balance"] is None and body["total"] == "0.00"

    def test_household_total_includes_every_account(self, client, h):
        body = get(client, "balances")
        assert len(body["accounts"]) == 2 and body["total"] == "5800.00"  # Cash has nothing


class TestSummary:
    def test_current_month(self, client, h):
        body = get(client, "dashboard/summary", **NOV)
        assert body["includes_projection"] is True
        assert body["income"] == {"realized": "5000.00", "total": "5000.00"}
        assert body["expenses"] == {"realized": "200.00", "total": "2000.00"}
        assert body["net"] == {"realized": "4800.00", "total": "3000.00"}
        assert body["fixed_expenses"] == {"total": "1800.00", "share": "0.9000"}

    def test_past_period_has_no_projection(self, client, h):
        body = get(client, "dashboard/summary", **{"from": "2026-10-01", "to": "2026-10-31"})
        assert body["includes_projection"] is False
        assert body["expenses"] == {"realized": "0.00", "total": "0.00"}  # overdue rent is not counted
        assert body["fixed_expenses"]["share"] is None

    def test_member_filter(self, client, h):
        assert get(client, "dashboard/summary", member_id=h["owner"], **NOV)["expenses"]["total"] == "2000.00"
        response = client.get("dashboard/summary", params={**NOV, "member_id": str(uuid.uuid4())})
        assert response.status_code == 404

    @pytest.mark.parametrize("to", ["2026-10-31", "2029-12-01"])
    def test_invalid_range(self, client, h, to):
        response = client.get("dashboard/summary", params={"from": "2026-11-01", "to": to})
        assert response.status_code == 422 and "to" in response.json()["error"]["fields"]


class TestProjection:
    def test_months_and_first_negative(self, client, h):
        body = get(client, "projection", **{"from": "2026-11-15", "to": "2027-02-10"})
        assert (body["from"], body["to"]) == ("2026-11-01", "2027-02-28")
        months = {m["month"]: m for m in body["months"]}
        assert list(months) == ["2026-11", "2026-12", "2027-01", "2027-02"]
        assert months["2026-11"]["expenses"] == {"realized": "200.00", "scheduled": "0.00", "projected_fixed": "1800.00", "total": "2000.00"}
        assert months["2027-01"]["expenses"] == {"realized": "0.00", "scheduled": "100.00", "projected_fixed": "1900.00", "total": "2000.00"}
        assert [m["end_balance"] for m in body["months"]] == ["4000.00", "2100.00", "100.00", "-1900.00"]
        assert [m["end_balance_projected"] for m in body["months"]] == [True] * 4
        assert months["2026-11"]["net"] == "3000.00"
        assert body["first_negative_month"] == "2027-02"

    def test_too_long(self, client, h):
        response = client.get("projection", params={"from": "2026-01-01", "to": "2029-01-31"})
        assert response.status_code == 422


class TestCategories:
    def test_expenses(self, client, h):
        body = get(client, "dashboard/categories", **NOV)
        assert body["type"] == "EXPENSE" and body["total"] == "2000.00"
        assert body["items"] == [
            {"category_id": h["cats"]["Rent"], "realized": "0.00", "total": "1800.00", "share": "0.9000"},
            {"category_id": h["cats"]["Food"], "realized": "200.00", "total": "200.00", "share": "0.1000"},
        ]

    def test_incomes(self, client, h):
        body = get(client, "dashboard/categories", type="INCOME", **NOV)
        assert [(i["category_id"], i["total"]) for i in body["items"]] == [(h["salary"], "5000.00")]


class TestCardBills:
    def test_next_bill(self, client, h):
        body = get(client, "cards/bills")
        assert body["items"] == [
            {"card_id": h["card"], "due_date": "2026-12-07", "closes_on": "2026-11-24", "rows_total": "100.00",
             "projected_fixed": "0.00", "total": "100.00", "rows_count": 1}  # fmt: skip
        ]

    def test_account_filter(self, client, h):
        cash = next(a["id"] for a in client.get("accounts").json()["items"] if a["type"] == "CASH")
        assert get(client, "cards/bills", account_id=cash)["items"] == []


class TestProjectionItems:
    def test_rows_and_occurrences(self, client, h):
        items = get(client, "projection/items", **NOV)["items"]
        assert [(i["type"], i["projected"], i["payment_date"]) for i in items] == [
            ("EXPENSE", True, "2026-11-25"), ("EXPENSE", False, "2026-11-10"), ("INCOME", False, "2026-11-05"),
        ]  # fmt: skip
        rent = items[0]
        assert rent["row"] is None and rent["converted"] == "1800.00"
        assert (rent["occurrence"]["status"], rent["occurrence"]["description"]) == ("PENDING", "Rent")
        assert items[1]["row"]["description"] == "Groceries" and items[1]["occurrence"] is None

    def test_pagination(self, client, h):
        first = get(client, "projection/items", limit=2, order="asc", **NOV)
        assert [i["payment_date"] for i in first["items"]] == ["2026-11-05", "2026-11-10"]
        second = get(client, "projection/items", limit=2, order="asc", cursor=first["next_cursor"], **NOV)
        assert [i["payment_date"] for i in second["items"]] == ["2026-11-25"]
        assert second["next_cursor"] is None

    def test_type_filter_and_bad_cursor(self, client, h):
        assert len(get(client, "projection/items", type="INCOME", **NOV)["items"]) == 1
        assert client.get("projection/items", params={**NOV, "cursor": "nope"}).status_code == 400


class TestCurrency:
    def test_historical_rate_and_unconverted(self, client, h, db):
        db.add(ExchangeRate(rate_date=date(2026, 11, 9), base=Currency.USD, quote=Currency.BRL, rate=Decimal("5.5"),
                            source="test", fetched_at=datetime(2026, 11, 9, tzinfo=timezone.utc)))  # fmt: skip
        db.flush()
        for currency in ("USD", "EUR"):
            post(client, "expenses", {"transaction_date": "2026-11-10", "currency": currency, "category_id": h["cats"]["Trips"],
                                      "total_amount": "10.00", "parts": [{"payment_method": "PIX", "account_id": h["bank"]}]})  # fmt: skip
        body = get(client, "dashboard/summary", **NOV)
        # USD uses the latest rate on or before Nov 10 (Nov 9); EUR has never been cached
        assert body["expenses"]["realized"] == "255.00"
        assert body["rates_as_of"] == "2026-11-09"
        assert body["unconverted"] == [{"currency": "EUR", "amount": "10.00"}]
