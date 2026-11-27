"""Transfers (specs/api.md §16, schemas §21).

The household from test_reports, seen on 2026-11-20: Nubank holds 5800.00 (opened with
1000.00 on 2026-10-31). Transfers move account balances on their date and change an
investment's amount right away.
"""

import pytest

from app.api.routes import investments as investment_routes
from app.api.routes import transfers as transfer_routes
from tests.api.conftest import csrf, signup
from tests.api.test_reports import TODAY, fixed_today, get, h, post  # noqa: F401 - fixtures

CDB = {
    "bank": "XP",
    "amount": "10000.00",
    "invested_on": "2026-11-01",
    "liquidity": "DAILY",
}


@pytest.fixture(autouse=True)
def transfers_today(monkeypatch):
    monkeypatch.setattr(transfer_routes, "today", lambda: TODAY)
    monkeypatch.setattr(investment_routes, "today", lambda: TODAY)


def account(client, name, balance="0.00", currency="BRL", opened="2026-10-31"):
    return post(client, "accounts", {"name": name, "opening_balance": balance, "currency": currency,
                                     "opening_balance_date": opened})["id"]  # fmt: skip


def end(kind, id_):
    return {"kind": kind, "id": id_}


def transfer(client, source, target, amount, **extra):
    return client.post("transfers", json={"source": source, "target": target, "amount": amount, **extra},
                       headers=csrf(client))  # fmt: skip


def balances(client, **params):
    body = get(client, "balances", **params)
    return body, {a["account_id"]: a["balance"] for a in body["accounts"]}


def amount_of(client, investment_id):
    return next(
        i["amount"]
        for i in get(client, "investments")["items"]
        if i["id"] == investment_id
    )


class TestAccounts:
    def test_moves_both_balances_and_keeps_the_total(self, client, h):
        savings = account(client, "Savings")
        before, _ = balances(client)
        response = transfer(
            client,
            end("ACCOUNT", h["bank"]),
            end("ACCOUNT", savings),
            "800.00",
            date="2026-11-12",
        )
        assert response.status_code == 201, response.json()
        body = response.json()
        assert (
            body["amount_sent"],
            body["amount_received"],
            body["currency_received"],
        ) == ("800.00", "800.00", "BRL")
        after, by_account = balances(client)
        assert (by_account[h["bank"]], by_account[savings]) == ("5000.00", "800.00")
        assert after["total"] == before["total"]

    def test_not_income_or_expense(self, client, h):
        savings = account(client, "Savings")
        before = get(
            client, "dashboard/summary", **{"from": "2026-11-01", "to": "2026-11-30"}
        )
        transfer(client, end("ACCOUNT", h["bank"]), end("ACCOUNT", savings), "800.00")
        after = get(
            client, "dashboard/summary", **{"from": "2026-11-01", "to": "2026-11-30"}
        )
        assert (after["income"], after["expenses"]) == (
            before["income"],
            before["expenses"],
        )

    def test_before_the_opening_date_is_already_in_the_balance(self, client, h):
        savings = account(client, "Savings", "300.00", opened="2026-11-15")
        transfer(
            client,
            end("ACCOUNT", h["bank"]),
            end("ACCOUNT", savings),
            "100.00",
            date="2026-11-10",
        )
        _, by_account = balances(client)
        assert (by_account[h["bank"]], by_account[savings]) == ("5700.00", "300.00")

    def test_different_currencies_need_the_amount_received(self, client, h):
        wallet = account(client, "Wise", currency="USD")
        response = transfer(
            client, end("ACCOUNT", h["bank"]), end("ACCOUNT", wallet), "550.00"
        )
        assert (
            response.status_code == 422
            and "amount_received" in response.json()["error"]["fields"]
        )
        response = transfer(
            client,
            end("ACCOUNT", h["bank"]),
            end("ACCOUNT", wallet),
            "550.00",
            amount_received="100.00",
        )
        assert response.status_code == 201, response.json()
        _, by_account = balances(client)
        assert (by_account[h["bank"]], by_account[wallet]) == ("5250.00", "100.00")

    @pytest.mark.parametrize(
        "extra, field",
        [
            ({"amount": "10.00", "date": "2026-11-21"}, "date"),
            ({"amount": "0.00"}, "amount"),
        ],
    )
    def test_invalid(self, client, h, extra, field):
        savings = account(client, "Savings")
        response = transfer(
            client, end("ACCOUNT", h["bank"]), end("ACCOUNT", savings), **extra
        )
        assert (
            response.status_code == 422 and field in response.json()["error"]["fields"]
        )

    def test_same_account(self, client, h):
        response = transfer(
            client, end("ACCOUNT", h["bank"]), end("ACCOUNT", h["bank"]), "10.00"
        )
        assert (
            response.status_code == 422
            and "target" in response.json()["error"]["fields"]
        )

    def test_account_with_transfers_is_in_use(self, client, h):
        savings = account(client, "Savings")
        transfer(client, end("ACCOUNT", h["bank"]), end("ACCOUNT", savings), "10.00")
        response = client.delete(f"accounts/{savings}", headers=csrf(client))
        assert (
            response.status_code == 409 and response.json()["error"]["code"] == "IN_USE"
        )


class TestInvestments:
    def test_into_an_investment(self, client, h):
        investment = post(client, "investments", CDB)["id"]
        before, _ = balances(client)
        response = transfer(
            client, end("ACCOUNT", h["bank"]), end("INVESTMENT", investment), "800.00"
        )
        assert response.status_code == 201, response.json()
        assert response.json()["target"] == {"kind": "INVESTMENT", "account_id": None, "investment_id": investment,
                                             "label": "XP"}  # fmt: skip
        assert amount_of(client, investment) == "10800.00"
        after, by_account = balances(client)
        assert by_account[h["bank"]] == "5000.00"
        assert after["total"] == before["total"]

    def test_out_of_an_investment(self, client, h):
        investment = post(client, "investments", CDB)["id"]
        response = transfer(
            client, end("INVESTMENT", investment), end("ACCOUNT", h["bank"]), "10000.01"
        )
        assert (
            response.status_code == 422
            and "amount" in response.json()["error"]["fields"]
        )
        response = transfer(
            client, end("INVESTMENT", investment), end("ACCOUNT", h["bank"]), "10000.00"
        )
        assert response.status_code == 201, response.json()
        assert amount_of(client, investment) == "0.00"  # redeemed
        _, by_account = balances(client)
        assert by_account[h["bank"]] == "15800.00"

    def test_delete_undoes_it(self, client, h):
        investment = post(client, "investments", CDB)["id"]
        made = transfer(
            client, end("ACCOUNT", h["bank"]), end("INVESTMENT", investment), "800.00"
        ).json()
        assert (
            client.delete(f"transfers/{made['id']}", headers=csrf(client)).status_code
            == 204
        )
        assert amount_of(client, investment) == "10000.00"
        _, by_account = balances(client)
        assert by_account[h["bank"]] == "5800.00"

    def test_delete_refused_when_the_money_left_the_investment(self, client, h):
        investment = post(client, "investments", CDB)["id"]
        made = transfer(
            client, end("ACCOUNT", h["bank"]), end("INVESTMENT", investment), "800.00"
        ).json()
        transfer(
            client, end("INVESTMENT", investment), end("ACCOUNT", h["bank"]), "10800.00"
        )
        assert (
            client.delete(f"transfers/{made['id']}", headers=csrf(client)).status_code
            == 409
        )

    def test_deleting_the_investment_keeps_the_transfer(self, client, h):
        investment = post(client, "investments", CDB)["id"]
        transfer(
            client, end("INVESTMENT", investment), end("ACCOUNT", h["bank"]), "500.00"
        )
        assert (
            client.delete(f"investments/{investment}", headers=csrf(client)).status_code
            == 204
        )
        items = get(client, "transfers")["items"]
        assert items[0]["source"] == {
            "kind": "INVESTMENT",
            "account_id": None,
            "investment_id": None,
            "label": "XP",
        }
        _, by_account = balances(client)
        assert by_account[h["bank"]] == "6300.00"


class TestList:
    def test_filters_and_order(self, client, h):
        savings = account(client, "Savings")
        investment = post(client, "investments", CDB)["id"]
        transfer(
            client,
            end("ACCOUNT", h["bank"]),
            end("ACCOUNT", savings),
            "1.00",
            date="2026-11-02",
        )
        transfer(
            client,
            end("ACCOUNT", h["bank"]),
            end("INVESTMENT", investment),
            "2.00",
            date="2026-11-15",
        )
        assert [t["amount_sent"] for t in get(client, "transfers")["items"]] == [
            "2.00",
            "1.00",
        ]
        assert len(get(client, "transfers", **{"from": "2026-11-10"})["items"]) == 1
        assert len(get(client, "transfers", account_id=savings)["items"]) == 1
        assert len(get(client, "transfers", investment_id=investment)["items"]) == 1

    def test_other_households(self, client, h):
        savings = account(client, "Savings")
        made = transfer(
            client, end("ACCOUNT", h["bank"]), end("ACCOUNT", savings), "1.00"
        ).json()
        client.cookies.clear()
        signup(client, email="other@example.com")
        assert get(client, "transfers")["items"] == []
        assert (
            client.delete(f"transfers/{made['id']}", headers=csrf(client)).status_code
            == 404
        )
        response = transfer(
            client, end("ACCOUNT", h["bank"]), end("ACCOUNT", savings), "1.00"
        )
        assert response.status_code == 404


def test_a_redeemed_investment_can_still_be_edited(client, h):
    investment = post(client, "investments", CDB)["id"]
    transfer(client, end("INVESTMENT", investment), end("ACCOUNT", h["bank"]), "10000.00")
    response = client.patch(f"investments/{investment}", json={"name": "Old CDB"}, headers=csrf(client))
    assert response.status_code == 200, response.json()
    response = client.patch(f"investments/{investment}", json={"amount": "-1.00"}, headers=csrf(client))
    assert response.status_code == 422
