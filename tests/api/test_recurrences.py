"""Recurrences and occurrences (specs/api.md §12, schemas §12-§13)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.routes import recurrences as recurrence_routes
from tests.api.conftest import csrf, signup

TODAY = date(2026, 11, 20)


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(recurrence_routes, "today", lambda: TODAY)


def post(client, path, json=None):
    return client.post(path, json=json, headers=csrf(client))


@pytest.fixture
def setup(client):
    owner = signup(client).json()
    bank = post(client, "accounts", {"name": "Nubank"}).json()
    card = post(client, "cards", {"alias": "NuCredit", "account_id": bank["id"], "best_buy_day": 25, "due_day": 5}).json()
    categories = {c["name"]: c["id"] for c in client.get("categories", params={"type": "EXPENSE"}).json()["items"]}
    salary = post(client, "categories", {"type": "INCOME", "name": "Salary"}).json()
    return {"owner": owner, "bank": bank["id"], "card": card["id"], "rent": categories["Rent"],
            "gym": categories["Gym"], "salary": salary["id"]}  # fmt: skip


def rent(client, setup, **extra):
    body = {"type": "EXPENSE", "amount": "1800.00", "payment_method": "CASH", "category_id": setup["rent"],
            "start_date": "2026-09-05", "description": "Rent", **extra}  # fmt: skip
    response = post(client, "recurrences", body)
    assert response.status_code == 201, response.json()
    return response.json()


def statuses(client, rec_id, start="2026-09-01", end="2027-01-31"):
    items = client.get(f"recurrences/{rec_id}/occurrences", params={"from": start, "to": end}).json()["items"]
    return [(o["occurrence_date"], o["status"]) for o in items]


class TestCreate:
    def test_defaults_and_next_occurrence(self, client, setup):
        body = rent(client, setup)
        rec = body["recurrence"]
        assert body["registered"] is None
        assert (rec["day_of_month"], rec["interval_months"], rec["status"], rec["currency"]) == (5, 1, "ACTIVE", "BRL")
        assert rec["next_occurrence"] == {"occurrence_date": "2026-11-05", "payment_date": "2026-11-05", "status": "PENDING"}

    def test_register_first_in_the_same_request(self, client, setup):
        body = rent(client, setup, start_date="2026-11-05",
                    register_first={"occurrence_date": "2026-11-05", "amount": "1750.00"})  # fmt: skip
        row = body["registered"]
        assert (row["amount"], row["occurrence_date"], row["recurrence_id"]) == ("1750.00", "2026-11-05", body["recurrence"]["id"])
        assert body["recurrence"]["next_occurrence"]["occurrence_date"] == "2026-12-05"

    @pytest.mark.parametrize(
        "extra,field",
        [
            ({"amount": "0.00"}, "amount"),
            ({"payment_method": "CREDIT"}, "card_id"),
            ({"payment_method": "PIX"}, "account_id"),
            ({"end_date": "2026-01-01"}, "end_date"),
            ({"interval_months": 13}, "interval_months"),
        ],
    )
    def test_invalid(self, client, setup, extra, field):
        body = {"type": "EXPENSE", "amount": "100.00", "payment_method": "CASH", "category_id": setup["rent"],
                "start_date": "2026-09-05", **extra}  # fmt: skip
        response = post(client, "recurrences", body)
        assert response.status_code == 422
        assert field in response.json()["error"]["fields"]

    def test_income_rules(self, client, setup):
        base = {"type": "INCOME", "amount": "9000.00", "payment_method": "PIX", "category_id": setup["salary"],
                "account_id": setup["bank"]}  # fmt: skip
        assert post(client, "recurrences", base).status_code == 201
        assert "card_id" in post(client, "recurrences", {**base, "card_id": setup["card"]}).json()["error"]["fields"]
        wrong_type = post(client, "recurrences", {**base, "category_id": setup["rent"]})
        assert wrong_type.json()["error"]["fields"] == {"category_id": ["Must be an income category"]}


class TestOccurrences:
    def test_statuses(self, client, setup):
        rec = rent(client, setup)["recurrence"]
        assert post(client, f"recurrences/{rec['id']}/occurrences/2026-10-05/register").status_code == 201
        assert post(client, f"recurrences/{rec['id']}/occurrences/2026-12-05/skip").status_code == 204
        assert statuses(client, rec["id"]) == [
            ("2026-09-05", "OVERDUE"),
            ("2026-10-05", "REGISTERED"),
            ("2026-11-05", "PENDING"),
            ("2026-12-05", "SKIPPED"),
            ("2027-01-05", "FUTURE"),
        ]
        assert post(client, f"recurrences/{rec['id']}/occurrences/2026-12-05/skip").status_code == 204  # idempotent
        assert client.delete(f"recurrences/{rec['id']}/occurrences/2026-12-05/skip", headers=csrf(client)).status_code == 204
        assert ("2026-12-05", "FUTURE") in statuses(client, rec["id"])

    def test_overdue_list_skips_paused_recurrences(self, client, setup):
        rec = rent(client, setup)["recurrence"]
        gym = rent(client, setup, category_id=setup["gym"], amount="120.00", start_date="2026-08-10")["recurrence"]
        post(client, f"recurrences/{gym['id']}/pause")
        overdue = client.get("occurrences/overdue").json()["items"]
        assert [(o["recurrence_id"], o["occurrence_date"]) for o in overdue] == [
            (rec["id"], "2026-09-05"), (rec["id"], "2026-10-05"),
        ]  # fmt: skip

    def test_register_rules(self, client, setup):
        rec = rent(client, setup)["recurrence"]
        base = f"recurrences/{rec['id']}/occurrences"
        assert post(client, f"{base}/2026-11-06/register").status_code == 404  # not an occurrence date
        assert post(client, f"{base}/2026-08-05/register").status_code == 404  # before start
        row = post(client, f"{base}/2026-11-05/register", {"amount": "1850.00", "transaction_date": "2026-11-07"}).json()
        assert (row["amount"], row["transaction_date"], row["payment_date"]) == ("1850.00", "2026-11-07", "2026-11-07")
        assert post(client, f"{base}/2026-11-05/register").status_code == 409
        post(client, f"{base}/2026-12-05/skip")
        assert post(client, f"{base}/2026-12-05/register").status_code == 409
        assert post(client, f"{base}/2026-11-05/skip").status_code == 409  # registered can't be skipped
        assert len(client.get("expenses", params={"fixed_only": True}).json()["items"]) == 1

    def test_credit_recurrence_occurs_on_the_card_due_dates(self, client, setup):
        # Card 25/5. A purchase on Nov 10 is on the statement due Dec 5 (a Saturday, paid Dec 7);
        # the client sends that due date as the first occurrence, with the purchase date.
        rec = rent(client, setup, payment_method="CREDIT", card_id=setup["card"], start_date="2026-12-05",
                   day_of_month=20, category_id=setup["gym"], amount="120.00",
                   register_first={"occurrence_date": "2026-12-05", "transaction_date": "2026-11-10"})  # fmt: skip
        created, row = rec["recurrence"], rec["registered"]
        assert (created["account_id"], created["day_of_month"]) == (setup["bank"], 5)  # the card's due day wins
        assert (row["card_id"], row["transaction_date"], row["payment_date"]) == (setup["card"], "2026-11-10", "2026-12-07")
        assert created["next_occurrence"]["occurrence_date"] == "2027-01-05"
        assert created["next_occurrence"]["payment_date"] == "2027-01-05"

    def test_credit_register_defaults_to_a_purchase_inside_the_statement(self, client, setup):
        rec = rent(client, setup, payment_method="CREDIT", card_id=setup["card"], start_date="2026-11-05",
                   category_id=setup["gym"], amount="120.00")["recurrence"]  # fmt: skip
        base = f"recurrences/{rec['id']}/occurrences"
        # Due Dec 5: purchases Oct 25 - Nov 24, so today (Nov 20) is used.
        row = post(client, f"{base}/2026-12-05/register").json()
        assert (row["transaction_date"], row["payment_date"]) == ("2026-11-20", "2026-12-07")
        # Due Nov 5: purchases Sep 25 - Oct 24, which already closed.
        row = post(client, f"{base}/2026-11-05/register").json()
        assert (row["transaction_date"], row["payment_date"]) == ("2026-10-24", "2026-11-05")
        # Due Jan 5: purchases Nov 25 - Dec 24, not open yet.
        row = post(client, f"{base}/2027-01-05/register").json()
        assert (row["transaction_date"], row["payment_date"]) == ("2026-11-25", "2027-01-05")

    def test_credit_recurrence_follows_the_card_due_day(self, client, setup):
        rec = rent(client, setup, payment_method="CREDIT", card_id=setup["card"], start_date="2026-11-05",
                   category_id=setup["gym"], amount="120.00")["recurrence"]  # fmt: skip
        base = f"recurrences/{rec['id']}/occurrences"
        post(client, f"{base}/2026-11-05/register")
        post(client, f"{base}/2026-12-05/skip")
        client.patch(f"cards/{setup['card']}", json={"due_day": 10}, headers=csrf(client))
        moved = client.get(f"recurrences/{rec['id']}").json()
        assert moved["day_of_month"] == 10
        assert moved["skipped_dates"] == ["2026-12-10"]
        assert statuses(client, rec["id"], "2026-11-01", "2027-01-31") == [
            ("2026-11-10", "REGISTERED"), ("2026-12-10", "SKIPPED"), ("2027-01-10", "FUTURE")
        ]

    def test_register_blocked_by_archived_category_until_fixed(self, client, setup):
        rec = rent(client, setup)["recurrence"]
        post(client, f"categories/{setup['rent']}/archive")
        response = post(client, f"recurrences/{rec['id']}/occurrences/2026-11-05/register")
        assert response.json()["error"]["fields"] == {"category_id": ["Category is archived"]}

    def test_deleting_the_payment_makes_the_occurrence_pending_again(self, client, setup):
        rec = rent(client, setup)["recurrence"]
        row = post(client, f"recurrences/{rec['id']}/occurrences/2026-11-05/register").json()
        assert client.delete(f"expenses/{row['id']}", headers=csrf(client)).status_code == 204
        assert ("2026-11-05", "PENDING") in statuses(client, rec["id"])


class TestLifecycle:
    def test_pause_resume_end(self, client, setup):
        rec = rent(client, setup)["recurrence"]
        paused = post(client, f"recurrences/{rec['id']}/pause").json()
        assert (paused["status"], paused["next_occurrence"]) == ("PAUSED", None)
        assert post(client, f"recurrences/{rec['id']}/resume").json()["status"] == "ACTIVE"
        ended = post(client, f"recurrences/{rec['id']}/end", {"end_date": "2026-10-31"}).json()
        assert (ended["status"], ended["end_date"], ended["next_occurrence"]) == ("ENDED", "2026-10-31", None)
        assert post(client, f"recurrences/{rec['id']}/end", {"end_date": "2026-01-01"}).status_code == 422

    def test_list_filters(self, client, setup):
        rent(client, setup)
        ended = rent(client, setup, category_id=setup["gym"], end_date="2026-10-31")["recurrence"]
        post(client, "recurrences", {"type": "INCOME", "amount": "9000.00", "payment_method": "PIX",
                                     "category_id": setup["salary"], "account_id": setup["bank"]})  # fmt: skip
        assert len(client.get("recurrences").json()["items"]) == 2  # active only by default
        assert [r["id"] for r in client.get("recurrences", params={"status": "ended"}).json()["items"]] == [ended["id"]]
        assert len(client.get("recurrences", params={"status": "all"}).json()["items"]) == 3
        assert len(client.get("recurrences", params={"type": "INCOME"}).json()["items"]) == 1

    def test_patch_revalidates_payment(self, client, setup):
        rec = rent(client, setup)["recurrence"]
        response = client.patch(f"recurrences/{rec['id']}", json={"payment_method": "PIX"}, headers=csrf(client))
        assert response.json()["error"]["fields"] == {"account_id": ["Required for this payment method"]}
        updated = client.patch(f"recurrences/{rec['id']}", json={"payment_method": "PIX", "account_id": setup["bank"],
                                                                 "amount": "1900.00"}, headers=csrf(client)).json()  # fmt: skip
        assert (updated["payment_method"], updated["account_id"], updated["amount"]) == ("PIX", setup["bank"], "1900.00")

    def test_change_amount_from_a_date(self, client, setup):
        rec = rent(client, setup)["recurrence"]
        base = f"recurrences/{rec['id']}/occurrences"
        post(client, f"{base}/2026-11-05/register")
        ahead = post(client, f"{base}/2027-01-05/register").json()  # paid in advance

        response = post(client, f"recurrences/{rec['id']}/change-amount", {"effective_date": "2026-12-05", "amount": "1950.00"})
        assert response.status_code == 200, response.json()
        ended, created = response.json()["ended"], response.json()["created"]
        assert (ended["end_date"], ended["amount"]) == ("2026-12-04", "1800.00")
        assert (created["start_date"], created["amount"], created["day_of_month"]) == ("2026-12-05", "1950.00", 5)
        # The advance payment now belongs to the new recurrence: it's not shown as unpaid there
        assert ("2027-01-05", "REGISTERED") in statuses(client, created["id"])
        assert client.get(f"expenses/{ahead['id']}").json()["recurrence_id"] == created["id"]
        assert ("2026-11-05", "REGISTERED") in statuses(client, rec["id"])

        too_early = post(client, f"recurrences/{created['id']}/change-amount", {"effective_date": "2026-12-05", "amount": "1.00"})
        assert "effective_date" in too_early.json()["error"]["fields"]

    def test_delete(self, client, setup):
        used = rent(client, setup)["recurrence"]
        post(client, f"recurrences/{used['id']}/occurrences/2026-11-05/register")
        response = client.delete(f"recurrences/{used['id']}", headers=csrf(client))
        assert response.status_code == 409 and response.json()["error"]["usage"]["expenses"] == 1
        unused = rent(client, setup, category_id=setup["gym"])["recurrence"]
        assert client.delete(f"recurrences/{unused['id']}", headers=csrf(client)).status_code == 204

    def test_other_household_is_not_found(self, client, setup):
        rec = rent(client, setup)["recurrence"]
        other = TestClient(client.app, base_url=str(client.base_url))
        signup(other, email="x@example.com")
        assert other.get(f"recurrences/{rec['id']}").status_code == 404
        assert other.get("occurrences/overdue").json()["items"] == []
