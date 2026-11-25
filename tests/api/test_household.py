"""Household, members, invitations and profile (specs/api.md §4-§6, schemas §4-§6)."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.clock import utcnow
from app.domain.enums import InvitationStatus
from app.models import Category, Household, Invitation, User
from tests.api.conftest import csrf, signup
from tests.db.factories import make_bank_account, make_card, make_expense


def new_client(client: TestClient) -> TestClient:
    return TestClient(client.app, base_url=str(client.base_url))


def invite(client: TestClient, email: str):
    return client.post("invitations", json={"email": email}, headers=csrf(client))


def invite_and_join(client: TestClient, outbox, email="ana@example.com", name="Ana Silva") -> TestClient:
    assert invite(client, email).status_code == 201
    other = new_client(client)
    response = signup(other, email=email, name=name, invitation_token=outbox.last_link_token())
    assert response.status_code == 201, response.json()
    return other


@pytest.fixture
def owner(client):
    return signup(client).json()


class TestHousehold:
    def test_get_and_patch(self, client, owner):
        assert client.get("household").json()["name"] == "Marcelo's household"
        response = client.patch(
            "household", json={"name": "Casa", "default_currency": "USD"}, headers=csrf(client)
        )
        assert response.status_code == 200
        assert (response.json()["name"], response.json()["default_currency"]) == ("Casa", "USD")
        assert client.get("auth/me").json()["household"]["default_currency"] == "USD"

    @pytest.mark.parametrize(
        "body,field", [({"name": None}, "name"), ({"name": ""}, "name"), ({"default_currency": "JPY"}, "default_currency")]
    )
    def test_invalid_patch(self, client, owner, body, field):
        response = client.patch("household", json=body, headers=csrf(client))
        assert response.status_code == 422
        assert field in response.json()["error"]["fields"]

    def test_requires_auth_and_csrf(self, client, owner):
        assert client.patch("household", json={"name": "X"}).status_code == 403
        client.cookies.clear()
        assert client.get("household").status_code == 401


class TestMembers:
    def test_list_marks_you(self, client, outbox, owner):
        invite_and_join(client, outbox)
        items = client.get("household/members").json()["items"]
        assert [(m["name"], m["is_you"]) for m in items] == [("Ana Silva", False), ("Marcelo Coelho", True)]

    def test_remove_moves_member_out_and_keeps_data(self, client, outbox, owner, db):
        ana_client = invite_and_join(client, outbox)
        ana = db.scalar(select(User).where(User.email == "ana@example.com"))
        household_id = owner["household"]["id"]
        household = db.get(Household, household_id)
        account = make_bank_account(db, household)
        card = make_card(db, household, ana, account, alias="AnaCard")
        expense = make_expense(db, household, ana)
        db.commit()

        response = client.delete(f"household/members/{ana.id}", headers=csrf(client))
        assert response.status_code == 204
        db.refresh(ana)
        db.refresh(card)
        db.refresh(expense)

        # Ana has her own new household with seed data, and her sessions ended
        assert str(ana.household_id) != household_id
        assert db.scalar(select(func.count()).select_from(Category).where(Category.household_id == ana.household_id)) == 28
        assert ana_client.get("auth/me").status_code == 401
        # Data stays behind; her cards are archived; she is now a former member
        assert str(expense.household_id) == household_id
        assert card.is_active is False
        assert client.get(f"users/{ana.id}").json() == {"id": str(ana.id), "name": "Ana Silva", "is_current_member": False}
        assert len(client.get("household/members").json()["items"]) == 1

    def test_remove_errors(self, client, outbox, owner):
        me_id = owner["user"]["id"]
        assert client.delete(f"household/members/{me_id}", headers=csrf(client)).status_code == 422
        outsider = signup(new_client(client), email="x@example.com").json()["user"]["id"]
        assert client.delete(f"household/members/{outsider}", headers=csrf(client)).status_code == 404

    def test_last_member_cannot_leave(self, client, owner):
        response = client.post("household/leave", headers=csrf(client))
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "LAST_MEMBER"

    def test_leave_keeps_session_in_new_household(self, client, outbox, owner):
        ana_client = invite_and_join(client, outbox)
        response = ana_client.post("household/leave", headers=csrf(ana_client))
        assert response.status_code == 200
        new_household = response.json()["household"]
        assert new_household["id"] != owner["household"]["id"]
        assert new_household["name"] == "Ana's household"
        assert ana_client.get("auth/me").json()["household"]["id"] == new_household["id"]
        assert [m["name"] for m in client.get("household/members").json()["items"]] == ["Marcelo Coelho"]

    def test_unrelated_users_are_not_visible(self, client, owner):
        outsider = signup(new_client(client), email="x@example.com").json()["user"]["id"]
        assert client.get(f"users/{outsider}").status_code == 404
        me = client.get(f"users/{owner['user']['id']}").json()
        assert me["is_current_member"] is True


class TestInvitations:
    def test_create_sends_email_and_never_returns_token(self, client, outbox, owner):
        response = invite(client, "  Ana@Example.com ")
        assert response.status_code == 201
        body = response.json()
        assert body["email"] == "ana@example.com" and body["status"] == "PENDING"
        assert "token" not in str(body).lower()
        message = outbox.messages[-1]
        assert message.to == "ana@example.com"
        assert "Marcelo convidou você" in message.text
        lookup = client.get("invitations/lookup", params={"token": outbox.last_link_token()})
        assert lookup.status_code == 200
        assert [i["id"] for i in client.get("invitations").json()["items"]] == [body["id"]]

    def test_one_pending_per_email(self, client, owner):
        invite(client, "ana@example.com")
        response = invite(client, "ana@example.com")
        assert response.status_code == 409

    def test_existing_account_is_rejected(self, client, owner):
        signup(new_client(client), email="taken@example.com")
        response = invite(client, "taken@example.com")
        assert response.status_code == 422
        assert response.json()["error"]["fields"] == {"email": ["This email already has an account"]}

    def test_resend_revokes_and_reissues(self, client, outbox, owner, db):
        first = invite(client, "ana@example.com").json()
        first_token = outbox.last_link_token()
        response = client.post(f"invitations/{first['id']}/resend", headers=csrf(client))
        assert response.status_code == 201
        second = response.json()
        assert second["id"] != first["id"]
        assert db.get(Invitation, first["id"]).status is InvitationStatus.REVOKED
        assert client.get("invitations/lookup", params={"token": first_token}).status_code == 410
        assert client.get("invitations/lookup", params={"token": outbox.last_link_token()}).status_code == 200

    def test_expired_invitation_can_be_replaced(self, client, owner, db):
        first = invite(client, "ana@example.com").json()
        db.get(Invitation, first["id"]).expires_at = utcnow() - timedelta(seconds=1)
        db.flush()
        assert client.get("invitations").json()["items"] == []
        assert invite(client, "ana@example.com").status_code == 201
        assert db.get(Invitation, first["id"]).status is InvitationStatus.EXPIRED

    def test_revoke(self, client, outbox, owner):
        invitation = invite(client, "ana@example.com").json()
        token = outbox.last_link_token()
        assert client.post(f"invitations/{invitation['id']}/revoke", headers=csrf(client)).status_code == 204
        assert client.get("invitations").json()["items"] == []
        assert client.get("invitations/lookup", params={"token": token}).status_code == 410

    def test_accepted_invitation_cannot_be_resent_or_revoked(self, client, outbox, owner):
        invitation = invite(client, "ana@example.com").json()
        signup(new_client(client), email="ana@example.com", invitation_token=outbox.last_link_token())
        assert client.post(f"invitations/{invitation['id']}/resend", headers=csrf(client)).status_code == 409
        assert client.post(f"invitations/{invitation['id']}/revoke", headers=csrf(client)).status_code == 409

    def test_other_households_invitations_are_not_found(self, client, owner):
        other = new_client(client)
        signup(other, email="x@example.com")
        foreign = invite(other, "ana@example.com").json()
        assert client.post(f"invitations/{foreign['id']}/revoke", headers=csrf(client)).status_code == 404

    def test_email_failure_returns_502_but_keeps_invitation(self, client, outbox, owner):
        outbox.fail = True
        response = invite(client, "ana@example.com")
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "EMAIL_FAILED"
        assert len(client.get("invitations").json()["items"]) == 1

    def test_rate_limit(self, client, owner):
        for i in range(20):
            assert invite(client, f"guest{i}@example.com").status_code == 201
        assert invite(client, "one-more@example.com").status_code == 429


class TestProfile:
    def test_get_never_exposes_password(self, client, owner):
        body = client.get("me").json()
        assert body["email"] == "marcelo@example.com"
        assert "password_hash" not in body and body["address"] is None

    def test_patch_normalizes_values(self, client, owner):
        response = client.patch(
            "me",
            json={
                "cpf": "12345678909",
                "phone": "+55 (48) 99999-9999",
                "birth_date": "1990-05-20",
                "address": {"cep": "88303575", "street": "Rua X", "number": "S/N", "city": "Itajaí", "state": "sc"},
                "notes": "  ",
            },
            headers=csrf(client),
        )
        assert response.status_code == 200, response.json()
        body = response.json()
        assert body["phone"] == "+5548999999999"
        assert body["address"]["state"] == "SC" and body["address"]["neighborhood"] is None
        assert body["notes"] is None

        cleared = client.patch("me", json={"address": None, "cpf": None}, headers=csrf(client)).json()
        assert cleared["address"] is None and cleared["cpf"] is None
        assert cleared["phone"] == "+5548999999999"  # omitted fields are unchanged

    @pytest.mark.parametrize(
        "body,field",
        [
            ({"cpf": "12345678900"}, "cpf"),
            ({"phone": "48999999999"}, "phone"),
            ({"birth_date": "2999-01-01"}, "birth_date"),
            ({"address": {"cep": "8830-357", "street": "R", "city": "C", "state": "SC"}}, "address.cep"),
            ({"address": {"cep": "88303575", "street": "R", "city": "C", "state": "XX"}}, "address.state"),
            ({"address": {"cep": "88303575", "street": "R", "state": "SC"}}, "address.city"),
            ({"name": None}, "name"),
            ({"email": "nope"}, "email"),
        ],
    )
    def test_invalid_fields(self, client, owner, body, field):
        response = client.patch("me", json=body, headers=csrf(client))
        assert response.status_code == 422
        assert field in response.json()["error"]["fields"]

    def test_email_change_and_conflicts(self, client, owner):
        other = new_client(client)
        signup(other, email="x@example.com")
        other.patch("me", json={"cpf": "11144477735"}, headers=csrf(other))

        assert client.patch("me", json={"email": "X@example.com"}, headers=csrf(client)).status_code == 409
        assert client.patch("me", json={"cpf": "11144477735"}, headers=csrf(client)).status_code == 409
        changed = client.patch("me", json={"email": "New@Example.com"}, headers=csrf(client))
        assert changed.json()["email"] == "new@example.com"
