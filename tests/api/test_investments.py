"""Investments (specs/api.md §15, schemas §20).

The household from test_reports: Nubank has 5800.00 on 2026-11-20 and 2100.00 projected
on 2026-12-31. Investments add to the total only when `include_in_balance` is on, from
the day they were made.
"""

import pytest

from app.api.routes import investments as investment_routes
from tests.api.conftest import csrf
from tests.api.test_reports import TODAY, fixed_today, get, h, post  # noqa: F401 - fixtures

CDB = {"name": "CDB 110%", "bank": "XP", "amount": "10000.00", "invested_on": "2026-11-01",
       "liquidity": "MATURITY", "maturity_date": "2028-11-01"}  # fmt: skip


@pytest.fixture(autouse=True)
def investments_today(monkeypatch):
    monkeypatch.setattr(investment_routes, "today", lambda: TODAY)


def patch(client, investment_id, body):
    return client.patch(f"investments/{investment_id}", json=body, headers=csrf(client))


class TestCrud:
    def test_create_defaults_and_list(self, client, h):
        created = post(client, "investments", {"bank": "Nubank", "amount": "500.00", "liquidity": "DAILY"})
        assert created["currency"] == "BRL" and created["invested_on"] == "2026-11-20"
        assert created["include_in_balance"] is True and created["maturity_date"] is None
        post(client, "investments", CDB)
        items = get(client, "investments")["items"]
        # Daily liquidity first, then by due date
        assert [i["bank"] for i in items] == ["Nubank", "XP"]

    @pytest.mark.parametrize(
        "body, field",
        [
            ({**CDB, "maturity_date": None}, "maturity_date"),
            ({**CDB, "maturity_date": "2026-11-01"}, "maturity_date"),
            ({**CDB, "liquidity": "DAILY"}, "maturity_date"),
            ({**CDB, "amount": "0.00"}, "amount"),
            ({**CDB, "bank": "  "}, "bank"),
        ],
    )
    def test_invalid(self, client, h, body, field):
        response = client.post("investments", json=body, headers=csrf(client))
        assert response.status_code == 422
        assert field in response.json()["error"]["fields"]

    def test_patch_to_daily_drops_the_due_date(self, client, h):
        investment = post(client, "investments", CDB)
        response = patch(client, investment["id"], {"liquidity": "DAILY"})
        assert response.status_code == 200, response.json()
        assert response.json()["maturity_date"] is None
        assert patch(client, investment["id"], {"bank": None}).status_code == 422

    def test_delete_and_other_households(self, client, h):
        investment = post(client, "investments", CDB)
        assert client.delete(f"investments/{investment['id']}", headers=csrf(client)).status_code == 204
        assert client.delete(f"investments/{investment['id']}", headers=csrf(client)).status_code == 404


class TestBalance:
    def test_included_investments_add_to_the_total(self, client, h):
        post(client, "investments", CDB)
        post(client, "investments", {**CDB, "bank": "Inter", "amount": "50.00", "include_in_balance": False})
        body = get(client, "balances")
        assert (body["total"], body["investments"]) == ("15800.00", "10000.00")
        assert all(a["account_id"] for a in body["accounts"])  # investments aren't listed as accounts

    def test_only_from_the_day_invested(self, client, h):
        post(client, "investments", {**CDB, "invested_on": "2026-12-15"})
        assert get(client, "balances")["investments"] == "0.00"
        later = get(client, "balances", date="2026-12-31")
        assert (later["total"], later["investments"]) == ("12100.00", "10000.00")

    def test_account_filter_leaves_them_out(self, client, h):
        post(client, "investments", CDB)
        body = get(client, "balances", account_id=h["bank"])
        assert (body["total"], body["investments"]) == ("5800.00", "0.00")

    def test_toggle_updates_the_total(self, client, h):
        investment = post(client, "investments", CDB)
        patch(client, investment["id"], {"include_in_balance": False})
        assert get(client, "balances")["total"] == "5800.00"

    def test_projection_end_balance(self, client, h):
        post(client, "investments", {**CDB, "invested_on": "2026-12-15"})
        months = get(client, "projection", **{"from": "2026-11-01", "to": "2026-12-31"})["months"]
        assert [(m["end_investments"], m["end_balance"]) for m in months] == [
            ("0.00", "4000.00"),  # 5800 - rent on Nov 25
            ("10000.00", "12100.00"),
        ]
