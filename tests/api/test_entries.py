"""Expenses and incomes (specs/api.md §10-§11, schemas §10-§11)."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.domain.enums import Currency
from app.models import ExchangeRate, Expense
from tests.api.conftest import csrf, signup


def post(client, path, json=None, **params):
    return client.post(path, json=json, params=params, headers=csrf(client))


def patch(client, path, json, **params):
    return client.patch(path, json=json, params=params, headers=csrf(client))


def delete(client, path, **params):
    return client.delete(path, params=params, headers=csrf(client))


@pytest.fixture
def setup(client):
    """A household with a bank account, a credit card (25/5), a debit card and categories."""
    owner = signup(client).json()
    bank = post(client, "accounts", {"name": "Nubank"}).json()
    credit = post(client, "cards", {"alias": "NuCredit", "account_id": bank["id"], "best_buy_day": 25, "due_day": 5}).json()
    debit = post(client, "cards", {"alias": "NuDebit", "account_id": bank["id"], "type": "DEBIT"}).json()
    cash = next(a for a in client.get("accounts").json()["items"] if a["type"] == "CASH")
    expense_categories = {c["name"]: c["id"] for c in client.get("categories", params={"type": "EXPENSE"}).json()["items"]}
    salary = next(c for c in client.get("categories", params={"type": "INCOME"}).json()["items"] if c["name"] == "Salary")
    return {
        "owner": owner, "bank": bank["id"], "cash": cash["id"], "credit": credit["id"], "debit": debit["id"],
        "food": expense_categories["Food"], "car": expense_categories["Car"], "salary": salary["id"],
    }  # fmt: skip


def expense(setup, total="100.00", parts=None, **extra):
    return {
        "transaction_date": "2026-11-10",
        "category_id": setup["food"],
        "total_amount": total,
        "parts": parts or [{"payment_method": "CASH"}],
        **extra,
    }


def create(client, body):
    response = post(client, "expenses", body)
    assert response.status_code == 201, response.json()
    return response.json()


def credit_series(client, setup, total="100.00", installments=3):
    return create(
        client,
        expense(setup, total, [{"payment_method": "CREDIT", "card_id": setup["credit"], "installments": installments}]),
    )["items"]


def summary(rows):
    return [(r["installment_number"], r["amount"], r["payment_date"]) for r in rows]


class TestCreate:
    def test_single_cash_expense_defaults(self, client, setup):
        body = create(client, expense(setup))
        assert body["split_group_id"] is None
        (row,) = body["items"]
        assert row["account_id"] == setup["cash"]
        assert row["payment_date"] == row["transaction_date"] == "2026-11-10"
        assert (row["amount"], row["currency"], row["installment_group_id"]) == ("100.00", "BRL", None)
        assert row["spender_id"] == row["created_by_id"] == setup["owner"]["user"]["id"]

    def test_credit_installments_follow_the_spec_example(self, client, setup):
        rows = credit_series(client, setup)
        assert summary(rows) == [
            (1, "33.34", "2026-12-07"),  # Dec 5 2026 is a Saturday
            (2, "33.33", "2027-01-05"),
            (3, "33.33", "2027-02-05"),
        ]
        assert len({r["installment_group_id"] for r in rows}) == 1 and rows[0]["installment_group_id"]
        assert {r["account_id"] for r in rows} == {setup["bank"]}  # the card's paying account

    def test_split_payment(self, client, setup):
        body = create(
            client,
            expense(setup, "150.00", [
                {"payment_method": "PIX", "account_id": setup["bank"], "amount": "50.00"},
                {"payment_method": "CREDIT", "card_id": setup["credit"], "amount": "100.00", "installments": 3},
            ]),
        )  # fmt: skip
        rows = body["items"]
        assert len(rows) == 4 and body["split_group_id"]
        assert {r["split_group_id"] for r in rows} == {body["split_group_id"]}
        assert [r["amount"] for r in rows] == ["50.00", "33.34", "33.33", "33.33"]
        assert rows[0]["installment_group_id"] is None

    @pytest.mark.parametrize(
        "parts,total,field",
        [
            ([{"payment_method": "CREDIT"}], "100.00", "parts[0].card_id"),
            ([{"payment_method": "CREDIT", "card_id": "DEBIT_CARD"}], "100.00", "parts[0].card_id"),
            ([{"payment_method": "DEBIT", "card_id": "DEBIT_CARD", "installments": 2}], "100.00", "parts[0].installments"),
            ([{"payment_method": "PIX"}], "100.00", "parts[0].account_id"),
            ([{"payment_method": "CASH", "account_id": "BANK"}], "100.00", "parts[0].account_id"),
            ([{"payment_method": "PIX", "account_id": "BANK", "card_id": "CREDIT_CARD"}], "100.00", "parts[0].card_id"),
            ([{"payment_method": "CASH", "amount": "90.00"}], "100.00", "parts[0].amount"),
            ([{"payment_method": "CASH", "amount": "40.00"}, {"payment_method": "PIX", "account_id": "BANK", "amount": "50.00"}], "100.00", "parts"),
            ([{"payment_method": "CASH"}, {"payment_method": "PIX", "account_id": "BANK", "amount": "50.00"}], "100.00", "parts[0].amount"),
            ([{"payment_method": "CASH", "installments": 3}], "0.02", "parts[0].installments"),
            ([{"payment_method": "CASH"}], "0.00", "total_amount"),
            ([{"payment_method": "CASH", "installments": 61}], "100.00", "parts.0.installments"),
        ],
    )
    def test_invalid_parts(self, client, setup, parts, total, field):
        ids = {"DEBIT_CARD": setup["debit"], "CREDIT_CARD": setup["credit"], "BANK": setup["bank"]}
        parts = [{k: ids.get(v, v) if isinstance(v, str) else v for k, v in p.items()} for p in parts]
        response = post(client, "expenses", expense(setup, total, parts))
        assert response.status_code == 422, response.json()
        fields = response.json()["error"]["fields"]
        assert field in fields or field.replace(".0.", "[0].") in fields, fields

    def test_category_must_match_type_and_spender_must_be_member(self, client, setup):
        response = post(client, "expenses", expense(setup, category_id=setup["salary"]))
        assert response.json()["error"]["fields"] == {"category_id": ["Must be an expense category"]}
        outsider = signup(TestClient(client.app, base_url=str(client.base_url)), email="x@example.com").json()
        response = post(client, "expenses", expense(setup, spender_id=outsider["user"]["id"]))
        assert "spender_id" in response.json()["error"]["fields"]

    def test_money_must_be_a_string(self, client, setup):
        response = post(client, "expenses", expense(setup, total=100))
        assert response.status_code == 422 and "total_amount" in response.json()["error"]["fields"]


class TestPreview:
    def test_returns_rows_without_saving(self, client, setup, db):
        body = expense(setup, "100.00", [{"payment_method": "CREDIT", "card_id": setup["credit"], "installments": 3}])
        response = post(client, "expenses/preview", body)
        assert response.status_code == 200
        preview = response.json()
        assert [(r["part"], r["amount"], r["payment_date"]) for r in preview["items"]] == [
            (0, "33.34", "2026-12-07"), (0, "33.33", "2027-01-05"), (0, "33.33", "2027-02-05"),
        ]  # fmt: skip
        assert preview["converted_total"] is None
        assert db.scalar(select(func.count()).select_from(Expense)) == 0

    def test_converted_total_uses_the_latest_rate(self, client, setup, db):
        db.add(ExchangeRate(rate_date=datetime(2026, 11, 19).date(), base=Currency.USD, quote=Currency.BRL,
                            rate=Decimal("5.4512"), source="test", fetched_at=datetime.now(timezone.utc)))  # fmt: skip
        db.flush()
        preview = post(client, "expenses/preview", expense(setup, "100.00", currency="USD")).json()
        assert preview["converted_total"] == {"amount": "545.12", "currency": "BRL"}

    def test_preview_validates_like_create(self, client, setup):
        response = post(client, "expenses/preview", expense(setup, parts=[{"payment_method": "PIX"}]))
        assert response.status_code == 422


class TestList:
    def test_pagination_and_order(self, client, setup):
        for day in ("2026-11-01", "2026-11-03", "2026-11-02", "2026-11-05", "2026-11-04"):
            create(client, expense(setup, transaction_date=day))
        page1 = client.get("expenses", params={"limit": 2}).json()
        page2 = client.get("expenses", params={"limit": 2, "cursor": page1["next_cursor"]}).json()
        page3 = client.get("expenses", params={"limit": 2, "cursor": page2["next_cursor"]}).json()
        days = [r["payment_date"] for p in (page1, page2, page3) for r in p["items"]]
        assert days == ["2026-11-05", "2026-11-04", "2026-11-03", "2026-11-02", "2026-11-01"]
        assert page3["next_cursor"] is None

    def test_filters(self, client, setup):
        credit_series(client, setup)
        create(client, expense(setup, description="Pão de 100% queijo"))
        create(client, expense(setup, category_id=setup["car"], transaction_date="2026-12-20"))

        def count(**params):
            return len(client.get("expenses", params=params).json()["items"])

        assert count() == 5
        assert count(card_id=setup["credit"]) == 3
        assert count(category_id=setup["car"]) == 1
        assert count(**{"from": "2026-12-01", "to": "2026-12-31"}) == 2  # credit installment 1 + car
        assert count(**{"from": "2026-12-01", "to": "2026-12-31", "date_field": "transaction_date"}) == 1
        assert count(q="100%") == 1  # LIKE wildcards are escaped
        assert count(payment_method="CREDIT") == 3
        assert count(fixed_only=True) == 0
        assert count(spender_id=setup["owner"]["user"]["id"]) == 5

    def test_invalid_cursor(self, client, setup):
        assert client.get("expenses", params={"cursor": "garbage"}).status_code == 400

    def test_other_households_rows_are_not_found(self, client, setup):
        row = create(client, expense(setup))["items"][0]
        other = TestClient(client.app, base_url=str(client.base_url))
        signup(other, email="x@example.com")
        assert other.get(f"expenses/{row['id']}").status_code == 404
        assert other.get("expenses").json()["items"] == []


class TestUpdate:
    def test_series_requires_scope(self, client, setup):
        rows = credit_series(client, setup)
        response = patch(client, f"expenses/{rows[1]['id']}", {"description": "x"})
        assert response.status_code == 422 and response.json()["error"]["code"] == "SCOPE_REQUIRED"

    def test_amount_with_scope_this_changes_one_row(self, client, setup):
        rows = credit_series(client, setup)
        items = patch(client, f"expenses/{rows[1]['id']}", {"amount": "40.00"}, scope="THIS").json()["items"]
        assert [r["amount"] for r in items] == ["33.34", "40.00", "33.33"]

    def test_payment_fields_need_scope_all(self, client, setup):
        rows = credit_series(client, setup)
        response = patch(client, f"expenses/{rows[1]['id']}", {"installments": 5}, scope="THIS")
        assert response.json()["error"]["fields"] == {"installments": ["Can only be changed with scope ALL"]}

    def test_scope_all_amount_is_the_new_total(self, client, setup):
        rows = credit_series(client, setup)
        items = patch(client, f"expenses/{rows[2]['id']}", {"amount": "90.00"}, scope="ALL").json()["items"]
        assert [r["amount"] for r in items] == ["30.00", "30.00", "30.00"]
        assert [r["id"] for r in items] == [r["id"] for r in rows]  # ids are stable

    def test_changing_installment_count_keeps_ids_and_redistributes(self, client, setup):
        rows = credit_series(client, setup)
        grown = patch(client, f"expenses/{rows[0]['id']}", {"installments": 5}, scope="ALL").json()["items"]
        assert [r["amount"] for r in grown] == ["20.00"] * 5
        assert [r["id"] for r in grown[:3]] == [r["id"] for r in rows]
        assert grown[4]["payment_date"] == "2027-04-05"

        shrunk = patch(client, f"expenses/{rows[2]['id']}", {"installments": 1}, scope="ALL").json()["items"]
        assert summary(shrunk) == [(1, "100.00", "2026-12-07")]
        assert shrunk[0]["installment_group_id"] is None and shrunk[0]["id"] == rows[0]["id"]
        assert len(client.get("expenses").json()["items"]) == 1

    def test_single_row_payment_change_recalculates_date(self, client, setup):
        row = create(client, expense(setup))["items"][0]
        items = patch(client, f"expenses/{row['id']}", {"payment_method": "CREDIT", "card_id": setup["credit"]}).json()["items"]
        assert (items[0]["payment_date"], items[0]["account_id"], items[0]["card_id"]) == ("2026-12-07", setup["bank"], setup["credit"])

    def test_single_row_into_series(self, client, setup):
        row = create(client, expense(setup))["items"][0]
        items = patch(client, f"expenses/{row['id']}", {"installments": 2}).json()["items"]
        assert [(r["installment_number"], r["amount"], r["payment_date"]) for r in items] == [
            (1, "50.00", "2026-11-10"), (2, "50.00", "2026-12-10"),
        ]  # fmt: skip

    def test_switching_method_validates_the_new_payment(self, client, setup):
        row = create(client, expense(setup))["items"][0]
        response = patch(client, f"expenses/{row['id']}", {"payment_method": "PIX"})
        assert response.json()["error"]["fields"] == {"account_id": ["Required for this payment method"]}

    def test_category_this_and_following(self, client, setup):
        rows = credit_series(client, setup)
        items = patch(client, f"expenses/{rows[1]['id']}", {"category_id": setup["car"]}, scope="THIS_AND_FOLLOWING").json()["items"]
        assert [r["category_id"] for r in items] == [setup["food"], setup["car"], setup["car"]]

    def test_split_shared_fields_apply_to_the_whole_purchase(self, client, setup):
        body = create(client, expense(setup, "150.00", [
            {"payment_method": "PIX", "account_id": setup["bank"], "amount": "50.00"},
            {"payment_method": "CREDIT", "card_id": setup["credit"], "amount": "100.00", "installments": 2},
        ]))  # fmt: skip
        pix = body["items"][0]
        items = patch(client, f"expenses/{pix['id']}", {"description": "Headphones", "transaction_date": "2026-11-26"}).json()["items"]
        assert {r["description"] for r in items} == {"Headphones"}
        assert {r["transaction_date"] for r in items} == {"2026-11-26"}
        credit_dates = sorted(r["payment_date"] for r in items if r["payment_method"] == "CREDIT")
        assert credit_dates == ["2027-01-05", "2027-02-05"]  # bought after the best day: next statement


class TestDelete:
    def test_series_requires_scope_and_does_not_renumber(self, client, setup):
        rows = credit_series(client, setup, installments=4)
        assert delete(client, f"expenses/{rows[1]['id']}").status_code == 422
        assert delete(client, f"expenses/{rows[2]['id']}", scope="THIS_AND_FOLLOWING").status_code == 204
        remaining = client.get("expenses").json()["items"]
        assert sorted((r["installment_number"], r["installment_total"]) for r in remaining) == [(1, 4), (2, 4)]

    def test_deleting_a_split_part_keeps_the_other_parts(self, client, setup):
        body = create(client, expense(setup, "150.00", [
            {"payment_method": "PIX", "account_id": setup["bank"], "amount": "50.00"},
            {"payment_method": "CREDIT", "card_id": setup["credit"], "amount": "100.00", "installments": 2},
        ]))  # fmt: skip
        credit_row = body["items"][1]
        assert delete(client, f"expenses/{credit_row['id']}", scope="ALL").status_code == 204
        remaining = client.get("expenses").json()["items"]
        assert [r["payment_method"] for r in remaining] == ["PIX"]


class TestIncomes:
    def income(self, setup, parts, **extra):
        return {"transaction_date": "2026-11-20", "category_id": setup["salary"], "total_amount": "1000.00",
                "parts": parts, **extra}  # fmt: skip

    def test_credit_income_is_same_day_next_month_on_a_business_day(self, client, setup):
        response = post(client, "incomes", self.income(setup, [{"payment_method": "CREDIT", "account_id": setup["bank"]}]))
        assert response.status_code == 201, response.json()
        row = response.json()["items"][0]
        assert row["payment_date"] == "2026-12-21"  # Dec 20 2026 is a Sunday
        assert row["receiver_id"] == setup["owner"]["user"]["id"] and "card_id" not in row

    def test_cash_income_and_bank_rules(self, client, setup):
        cash = post(client, "incomes", self.income(setup, [{"payment_method": "CASH"}])).json()["items"][0]
        assert cash["account_id"] == setup["cash"]
        response = post(client, "incomes", self.income(setup, [{"payment_method": "PIX"}]))
        assert response.json()["error"]["fields"] == {"parts[0].account_id": ["Required for this payment method"]}
        response = post(client, "incomes", self.income(setup, [{"payment_method": "CASH"}], category_id=setup["food"]))
        assert response.json()["error"]["fields"] == {"category_id": ["Must be an income category"]}

    def test_income_installments_and_receiver_filter(self, client, setup):
        rows = post(client, "incomes", self.income(setup, [{"payment_method": "PIX", "account_id": setup["bank"], "installments": 2}])).json()["items"]
        assert summary(rows) == [(1, "500.00", "2026-11-20"), (2, "500.00", "2026-12-20")]
        listed = client.get("incomes", params={"receiver_id": setup["owner"]["user"]["id"]}).json()["items"]
        assert len(listed) == 2
        assert client.get("expenses").json()["items"] == []
