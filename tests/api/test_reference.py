"""Accounts, cards and categories (specs/api.md §7-§9, schemas §7-§9, §18)."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.domain.enums import PaymentMethod
from app.models import Household, User
from tests.api.conftest import csrf, signup
from tests.db.factories import make_expense, make_household


@pytest.fixture
def owner(client):
    return signup(client).json()


def post(client: TestClient, path: str, json=None):
    return client.post(path, json=json, headers=csrf(client))


def patch(client: TestClient, path: str, json):
    return client.patch(path, json=json, headers=csrf(client))


def delete(client: TestClient, path: str):
    return client.delete(path, headers=csrf(client))


def new_bank(client, name="Nubank", **extra):
    response = post(client, "accounts", {"type": "BANK", "name": name, **extra})
    assert response.status_code == 201, response.json()
    return response.json()


def new_card(client, account_id, alias="Nubank", **extra):
    body = {"alias": alias, "account_id": account_id, "best_buy_day": 25, "due_day": 5, **extra}
    response = post(client, "cards", body)
    assert response.status_code == 201, response.json()
    return response.json()


class TestAccounts:
    def test_defaults_and_listing(self, client, owner):
        created = new_bank(client)
        assert created["currency"] == "BRL"
        assert created["opening_balance"] == "0.00"
        names = [a["name"] for a in client.get("accounts").json()["items"]]
        assert names == ["Nubank", "Cash"]  # BANK sorts before CASH

    def test_money_must_be_a_string(self, client, owner):
        response = post(client, "accounts", {"name": "Itaú", "opening_balance": 10.5})
        assert response.status_code == 422
        assert "opening_balance" in response.json()["error"]["fields"]
        assert post(client, "accounts", {"name": "Itaú", "opening_balance": "10.555"}).status_code == 422
        ok = post(client, "accounts", {"name": "Itaú", "opening_balance": "-320.5", "currency": "USD"})
        assert (ok.json()["opening_balance"], ok.json()["currency"]) == ("-320.50", "USD")

    def test_name_unique_case_insensitive(self, client, owner):
        new_bank(client, "Nubank")
        response = post(client, "accounts", {"name": "NUBANK"})
        assert response.status_code == 409 and "name" in response.json()["error"]["fields"]

    def test_patch_and_type_is_immutable(self, client, owner):
        account = new_bank(client)
        assert patch(client, f"accounts/{account['id']}", {"type": "CASH"}).status_code == 422
        updated = patch(client, f"accounts/{account['id']}", {"name": "Nu", "opening_balance": "100.00"}).json()
        assert (updated["name"], updated["opening_balance"]) == ("Nu", "100.00")

    def test_adjust_balance(self, client, owner):
        account = new_bank(client)
        response = post(client, f"accounts/{account['id']}/adjust", {"balance": "1180.00", "date": "2026-11-20"})
        assert response.status_code == 200
        assert (response.json()["opening_balance"], response.json()["opening_balance_date"]) == ("1180.00", "2026-11-20")

    def test_last_cash_account_is_protected(self, client, owner):
        cash = next(a for a in client.get("accounts").json()["items"] if a["type"] == "CASH")
        assert post(client, f"accounts/{cash['id']}/archive").status_code == 422
        assert delete(client, f"accounts/{cash['id']}").status_code == 422
        second = post(client, "accounts", {"type": "CASH", "name": "Wallet"}).json()
        assert post(client, f"accounts/{cash['id']}/archive").status_code == 200
        assert post(client, f"accounts/{second['id']}/archive").status_code == 422

    def test_archive_hides_and_unarchive_restores(self, client, owner):
        account = new_bank(client)
        post(client, f"accounts/{account['id']}/archive")
        assert account["id"] not in [a["id"] for a in client.get("accounts").json()["items"]]
        assert account["id"] in [a["id"] for a in client.get("accounts", params={"include_archived": True}).json()["items"]]
        assert post(client, f"accounts/{account['id']}/unarchive").json()["is_active"] is True

    def test_delete_in_use_reports_usage(self, client, owner):
        account = new_bank(client)
        new_card(client, account["id"])
        response = delete(client, f"accounts/{account['id']}")
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "IN_USE"
        assert error["usage"] == {"expenses": 0, "incomes": 0, "recurrences": 0, "cards": 1, "transfers": 0}

    def test_delete_unused(self, client, owner):
        account = new_bank(client)
        assert delete(client, f"accounts/{account['id']}").status_code == 204

    def test_other_households_records_are_not_found(self, client, owner):
        other = TestClient(client.app, base_url=str(client.base_url))
        signup(other, email="x@example.com")
        foreign = new_bank(other)
        assert patch(client, f"accounts/{foreign['id']}", {"name": "Mine"}).status_code == 404
        assert delete(client, f"accounts/{foreign['id']}").status_code == 404


class TestCards:
    def test_create_with_defaults(self, client, owner):
        account = new_bank(client)
        card = new_card(client, account["id"])
        assert card["owner_id"] == owner["user"]["id"]
        assert (card["type"], card["best_buy_day"], card["due_day"]) == ("CREDIT", 25, 5)

    @pytest.mark.parametrize(
        "body,field",
        [
            ({"alias": "Two words"}, "alias"),
            ({"best_buy_day": None}, "best_buy_day"),
            ({"type": "DEBIT"}, "best_buy_day"),  # debit card with days
            ({"due_day": 32}, "due_day"),
            ({"last_four": "12a4"}, "last_four"),
        ],
    )
    def test_invalid(self, client, owner, body, field):
        account = new_bank(client)
        base = {"alias": "Nubank", "account_id": account["id"], "best_buy_day": 25, "due_day": 5}
        response = post(client, "cards", {**base, **body})
        assert response.status_code == 422
        assert field in response.json()["error"]["fields"]

    def test_account_must_be_an_active_bank_account(self, client, owner):
        cash = next(a for a in client.get("accounts").json()["items"] if a["type"] == "CASH")
        body = {"alias": "Nubank", "account_id": cash["id"], "best_buy_day": 25, "due_day": 5}
        assert post(client, "cards", body).json()["error"]["fields"] == {"account_id": ["Must be a bank account"]}
        archived = new_bank(client)
        post(client, f"accounts/{archived['id']}/archive")
        body["account_id"] = archived["id"]
        assert post(client, "cards", body).json()["error"]["fields"] == {"account_id": ["Account is archived"]}

    def test_owner_must_be_a_member(self, client, owner):
        account = new_bank(client)
        other = TestClient(client.app, base_url=str(client.base_url))
        outsider = signup(other, email="x@example.com").json()["user"]["id"]
        response = post(client, "cards", {"alias": "X", "account_id": account["id"], "best_buy_day": 1,
                                          "due_day": 10, "owner_id": outsider})  # fmt: skip
        assert response.json()["error"]["fields"] == {"owner_id": ["Must be a current member of the household"]}

    def test_alias_unique_and_debit_card(self, client, owner):
        account = new_bank(client)
        new_card(client, account["id"], alias="Porto")
        assert post(client, "cards", {"alias": "porto", "account_id": account["id"], "best_buy_day": 1, "due_day": 9}).status_code == 409
        debit = new_card(client, account["id"], alias="NuDebit", type="DEBIT", best_buy_day=None, due_day=None)
        assert debit["best_buy_day"] is None

    def test_patch_validates_final_state(self, client, owner):
        account = new_bank(client)
        card = new_card(client, account["id"])
        # Switching to debit without clearing the days is rejected...
        assert patch(client, f"cards/{card['id']}", {"type": "DEBIT"}).status_code == 422
        # ...and accepted when the days are cleared in the same request.
        response = patch(client, f"cards/{card['id']}", {"type": "DEBIT", "best_buy_day": None, "due_day": None})
        assert response.status_code == 200 and response.json()["type"] == "DEBIT"

    def test_unarchive_requires_a_current_owner(self, client, owner, db):
        account = new_bank(client)
        card = new_card(client, account["id"])
        ana = User(household_id=owner["household"]["id"], name="Ana Silva", email="ana@example.com", password_hash="x")
        db.add(ana)
        db.flush()
        assert patch(client, f"cards/{card['id']}", {"owner_id": str(ana.id)}).status_code == 200
        post(client, f"cards/{card['id']}/archive")

        ana.household_id = make_household(db, "Ana Silva").id  # Ana leaves the household
        db.flush()
        response = post(client, f"cards/{card['id']}/unarchive")
        assert response.status_code == 422 and "owner_id" in response.json()["error"]["fields"]

        assert patch(client, f"cards/{card['id']}", {"owner_id": owner["user"]["id"]}).status_code == 200
        assert post(client, f"cards/{card['id']}/unarchive").json()["is_active"] is True

    def test_preview_matches_spec_example(self, client, owner):
        response = post(client, "cards/preview", {"best_buy_day": 25, "due_day": 5, "purchase_date": "2026-11-10"})
        assert response.json() == {"closing_date": "2026-11-25", "payment_date": "2026-12-07"}

    def test_delete_card_in_use(self, client, owner, db):
        account = new_bank(client)
        card = new_card(client, account["id"])
        household = db.get(Household, owner["household"]["id"])
        user = db.get(User, owner["user"]["id"])
        make_expense(db, household, user, payment_method=PaymentMethod.CREDIT, card_id=UUID(card["id"]),
                     account_id=UUID(account["id"]))  # fmt: skip
        response = delete(client, f"cards/{card['id']}")
        assert response.status_code == 409
        assert response.json()["error"]["usage"] == {"expenses": 1, "incomes": 0, "recurrences": 0}


class TestCategories:
    def test_list_requires_type(self, client, owner):
        assert client.get("categories").status_code == 422
        assert len(client.get("categories", params={"type": "EXPENSE"}).json()["items"]) == 25
        incomes = client.get("categories", params={"type": "INCOME"}).json()["items"]
        assert sorted((c["name"], c["seed_key"]) for c in incomes) == [
            ("Investments", "investments"), ("Other", "other"), ("Salary", "salary")
        ]

    def test_create_rename_and_uniqueness(self, client, owner):
        bonus = post(client, "categories", {"type": "INCOME", "name": "Bonus"}).json()
        assert bonus["seed_key"] is None
        assert post(client, "categories", {"type": "INCOME", "name": "salary"}).status_code == 409
        assert post(client, "categories", {"type": "EXPENSE", "name": "Bonus"}).status_code == 201
        salary = next(c for c in client.get("categories", params={"type": "INCOME"}).json()["items"] if c["name"] == "Salary")
        assert patch(client, f"categories/{salary['id']}", {"name": "Salary"}).json()["seed_key"] == "salary"  # unchanged
        renamed = patch(client, f"categories/{salary['id']}", {"name": "Wages"}).json()
        assert (renamed["name"], renamed["seed_key"]) == ("Wages", None)  # renamed: no longer translated
        assert patch(client, f"categories/{salary['id']}", {"name": "Food"}).status_code == 200  # Food is EXPENSE

    def test_archive_and_delete(self, client, owner, db):
        food = next(c for c in client.get("categories", params={"type": "EXPENSE"}).json()["items"] if c["name"] == "Food")
        household = db.get(Household, owner["household"]["id"])
        make_expense(db, household, db.get(User, owner["user"]["id"]))  # uses Food
        assert delete(client, f"categories/{food['id']}").json()["error"]["usage"]["expenses"] == 1
        assert post(client, f"categories/{food['id']}/archive").json()["is_active"] is False
        names = [c["name"] for c in client.get("categories", params={"type": "EXPENSE"}).json()["items"]]
        assert "Food" not in names
        gym = next(c for c in client.get("categories", params={"type": "EXPENSE"}).json()["items"] if c["name"] == "Gym")
        assert delete(client, f"categories/{gym['id']}").status_code == 204


def test_reference_routes_require_csrf(client, owner):
    assert client.post("accounts", json={"name": "X"}).status_code == 403
    assert client.post("cards/preview", json={"best_buy_day": 1, "due_day": 9}).status_code == 403
