"""specs/auth.md, end to end through the HTTP API."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.clock import utcnow
from app.core.security import hash_token
from app.domain.enums import AccountType, InvitationStatus
from app.models import Account, Category, Invitation, PasswordResetToken, Session, User
from tests.api.conftest import PASSWORD, csrf, signup


def session_count(db, user_id) -> int:
    return db.scalar(select(func.count()).select_from(Session).where(Session.user_id == user_id))


def user_by_email(db, email) -> User:
    return db.scalar(select(User).where(User.email == email))


def add_invitation(db, household_id, inviter_id, email, token="invite-token", **fields) -> Invitation:
    invitation = Invitation(
        household_id=household_id,
        email=email,
        token_hash=hash_token(token),
        invited_by_id=inviter_id,
        expires_at=fields.pop("expires_at", utcnow() + timedelta(days=7)),
        **fields,
    )
    db.add(invitation)
    db.flush()
    return invitation


class TestSignup:
    def test_creates_household_with_seed_data_and_logs_in(self, client, db):
        response = signup(client, email="  Marcelo@Example.COM ")
        assert response.status_code == 201
        body = response.json()
        assert body["user"]["email"] == "marcelo@example.com"
        assert body["household"] == {
            "id": body["user"]["household_id"],
            "name": "Marcelo's household",
            "default_currency": "BRL",
        }
        household_id = body["user"]["household_id"]
        assert db.scalar(select(func.count()).select_from(Category).where(Category.household_id == household_id)) == 25
        assert db.scalar(
            select(Account.name).where(Account.household_id == household_id, Account.type == AccountType.CASH)
        ) == "Cash"

        set_cookie = response.headers.get_list("set-cookie")
        session_cookie = next(c for c in set_cookie if c.startswith("brs_session="))
        csrf_cookie = next(c for c in set_cookie if c.startswith("brs_csrf="))
        assert "HttpOnly" in session_cookie and "SameSite=lax" in session_cookie
        assert "HttpOnly" not in csrf_cookie
        assert client.get("auth/me").json() == body

    def test_portuguese_seed_data(self, client, db):
        body = signup(client, language="pt").json()
        household_id = body["user"]["household_id"]
        assert body["user"]["language"] == "pt" and body["household"]["name"] == "Casa de Marcelo"
        names = set(db.scalars(select(Category.name).where(Category.household_id == household_id)))
        assert {"Aluguel", "Alimentação", "Outros"} <= names and len(names) == 25
        assert db.scalar(
            select(Account.name).where(Account.household_id == household_id, Account.type == AccountType.CASH)
        ) == "Dinheiro"

    def test_unknown_language(self, client):
        assert signup(client, language="es").status_code == 422

    def test_password_is_hashed_with_argon2(self, client, db):
        signup(client)
        assert user_by_email(db, "marcelo@example.com").password_hash.startswith("$argon2id$")

    def test_duplicate_email(self, client):
        signup(client)
        response = signup(client, email="MARCELO@example.com")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "EMAIL_TAKEN"

    def test_weak_passwords(self, client):
        short = client.post("auth/signup", json={"name": "Ana", "email": "a@example.com", "password": "1234567"})
        assert short.status_code == 422
        assert short.json()["error"]["fields"] == {"password": ["Must be at least 8 characters"]}

        same_as_email = client.post(
            "auth/signup", json={"name": "Ana", "email": "ana.silva@example.com", "password": "Ana.Silva@example.com"}
        )
        assert same_as_email.json()["error"]["fields"] == {"password": ["Must not be your email or your name"]}

    def test_validation_envelope(self, client):
        response = client.post("auth/signup", json={"name": "", "email": "not-an-email", "password": PASSWORD})
        error = response.json()["error"]
        assert response.status_code == 422
        assert error["code"] == "VALIDATION_ERROR"
        assert set(error["fields"]) == {"name", "email"}

    def test_malformed_json(self, client):
        response = client.post("auth/signup", content=b"{nope", headers={"content-type": "application/json"})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "BAD_REQUEST"

    def test_rate_limited_per_ip(self, client):
        for i in range(10):
            signup(client, email=f"user{i}@example.com")
        response = signup(client, email="eleventh@example.com")
        assert response.status_code == 429
        assert int(response.headers["Retry-After"]) > 0


class TestSignupWithInvitation:
    def setup_inviter(self, client, db):
        inviter = signup(client).json()["user"]
        client.cookies.clear()
        return inviter

    def test_joins_the_inviting_household(self, client, db):
        inviter = self.setup_inviter(client, db)
        invitation = add_invitation(db, inviter["household_id"], inviter["id"], "ana@example.com")

        response = signup(client, email="ana@example.com", name="Ana Silva", invitation_token="invite-token")
        assert response.status_code == 201
        assert response.json()["user"]["household_id"] == inviter["household_id"]
        db.refresh(invitation)
        assert invitation.status is InvitationStatus.ACCEPTED and invitation.accepted_at is not None
        # No extra household seed was created
        assert db.scalar(select(func.count()).select_from(Account).where(Account.household_id == inviter["household_id"])) == 1

        reused = signup(client, email="ana@example.com", invitation_token="invite-token")
        assert reused.status_code == 410

    def test_email_must_match_invitation(self, client, db):
        inviter = self.setup_inviter(client, db)
        add_invitation(db, inviter["household_id"], inviter["id"], "ana@example.com")
        response = signup(client, email="other@example.com", invitation_token="invite-token")
        assert response.status_code == 422
        assert "email" in response.json()["error"]["fields"]

    def test_expired_and_revoked_invitations(self, client, db):
        inviter = self.setup_inviter(client, db)
        add_invitation(db, inviter["household_id"], inviter["id"], "a@example.com", token="expired",
                       expires_at=utcnow() - timedelta(seconds=1))  # fmt: skip
        add_invitation(db, inviter["household_id"], inviter["id"], "b@example.com", token="revoked",
                       status=InvitationStatus.REVOKED)  # fmt: skip
        for email, token in (("a@example.com", "expired"), ("b@example.com", "revoked"), ("c@example.com", "nope")):
            response = signup(client, email=email, invitation_token=token)
            assert response.status_code == 410
            assert response.json()["error"]["code"] == "INVITATION_INVALID"

    def test_public_lookup(self, client, db):
        inviter = self.setup_inviter(client, db)
        add_invitation(db, inviter["household_id"], inviter["id"], "ana@example.com")
        response = client.get("invitations/lookup", params={"token": "invite-token"})
        assert response.json() == {
            "household_name": "Marcelo's household",
            "email": "ana@example.com",
            "invited_by_name": "Marcelo Coelho",
        }
        assert client.get("invitations/lookup", params={"token": "wrong"}).status_code == 410


class TestLogin:
    def test_success_creates_a_new_session(self, client, db):
        user_id = signup(client).json()["user"]["id"]
        client.cookies.clear()
        response = client.post("auth/login", json={"email": "MARCELO@example.com", "password": PASSWORD})
        assert response.status_code == 200
        assert response.json()["user"]["id"] == user_id
        assert session_count(db, user_id) == 2
        assert client.get("auth/me").status_code == 200

    def test_failures_are_generic(self, client):
        signup(client)
        wrong_password = client.post("auth/login", json={"email": "marcelo@example.com", "password": "wrong-pass"})
        unknown_email = client.post("auth/login", json={"email": "nobody@example.com", "password": "wrong-pass"})
        assert wrong_password.status_code == unknown_email.status_code == 401
        assert wrong_password.json() == unknown_email.json()
        assert wrong_password.json()["error"]["code"] == "INVALID_CREDENTIALS"

    def test_five_failures_lock_the_email(self, client):
        signup(client)
        for _ in range(5):
            client.post("auth/login", json={"email": "marcelo@example.com", "password": "wrong-pass"})
        response = client.post("auth/login", json={"email": "marcelo@example.com", "password": PASSWORD})
        assert response.status_code == 429
        assert 0 < int(response.headers["Retry-After"]) <= 15 * 60


class TestSessions:
    def test_me_requires_a_session(self, client):
        response = client.get("auth/me")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"

    def test_idle_and_absolute_expiry(self, client, db):
        user_id = signup(client).json()["user"]["id"]
        session = db.scalar(select(Session).where(Session.user_id == user_id))
        session.expires_at = utcnow() - timedelta(seconds=1)
        db.flush()
        assert client.get("auth/me").status_code == 401

        session.expires_at = utcnow() + timedelta(days=1)
        session.absolute_expires_at = utcnow() - timedelta(seconds=1)
        db.flush()
        assert client.get("auth/me").status_code == 401

    def test_stale_session_cookie_is_cleared(self, client, db):
        # e.g. the session was deleted or the database was reset: the 401 also clears the
        # cookies, so the UI's route guard stops treating the browser as logged in.
        client.cookies.set("brs_session", "no-such-session")
        client.cookies.set("brs_csrf", "stale")
        response = client.get("auth/me")
        assert response.status_code == 401
        cleared = response.headers.get_list("set-cookie")
        assert any(c.startswith('brs_session=""') or c.startswith("brs_session=;") for c in cleared), cleared
        assert any(c.startswith("brs_csrf=") and "Max-Age=0" in c for c in cleared), cleared

    def test_no_cookie_no_set_cookie(self, client):
        response = client.get("auth/me")
        assert response.status_code == 401 and "set-cookie" not in response.headers

    def test_activity_slides_the_idle_expiry(self, client, db):
        user_id = signup(client).json()["user"]["id"]
        session = db.scalar(select(Session).where(Session.user_id == user_id))
        stale = utcnow() - timedelta(days=10)
        session.last_seen_at, session.expires_at = stale, stale + timedelta(days=30)
        db.flush()
        assert client.get("auth/me").status_code == 200
        db.refresh(session)
        assert session.expires_at > utcnow() + timedelta(days=29)

    def test_household_is_resolved_on_every_request(self, client, db):
        body = signup(client).json()
        other = signup(TestClient(client.app, base_url=str(client.base_url)), email="x@example.com").json()
        user = db.get(User, body["user"]["id"])
        user.household_id = other["household"]["id"]
        db.flush()
        assert client.get("auth/me").json()["household"]["id"] == other["household"]["id"]


class TestLogoutAndCsrf:
    def test_logout_requires_csrf_and_ends_the_session(self, client, db):
        user_id = signup(client).json()["user"]["id"]
        assert client.post("auth/logout").status_code == 403
        response = client.post("auth/logout", headers=csrf(client))
        assert response.status_code == 204
        assert session_count(db, user_id) == 0
        assert client.get("auth/me").status_code == 401

    def test_logout_without_session_just_clears_cookies(self, client):
        assert client.post("auth/logout").status_code == 204

    def test_csrf_header_must_match_cookie(self, client):
        signup(client)
        body = {"current_password": PASSWORD, "new_password": "another good one"}
        assert client.post("auth/password", json=body).json()["error"]["code"] == "CSRF_FAILED"
        assert client.post("auth/password", json=body, headers={"X-CSRF-Token": "forged"}).status_code == 403
        assert client.post("auth/password", json=body, headers=csrf(client)).status_code == 204


class TestChangePassword:
    def test_keeps_current_session_and_ends_the_others(self, client, db, outbox):
        user_id = signup(client).json()["user"]["id"]
        other_device = TestClient(client.app, base_url=str(client.base_url))
        other_device.post("auth/login", json={"email": "marcelo@example.com", "password": PASSWORD})
        assert session_count(db, user_id) == 2

        response = client.post(
            "auth/password",
            json={"current_password": PASSWORD, "new_password": "brand new secret"},
            headers=csrf(client),
        )
        assert response.status_code == 204
        assert session_count(db, user_id) == 1
        assert client.get("auth/me").status_code == 200
        assert other_device.get("auth/me").status_code == 401
        assert outbox.messages[-1].subject == "Sua senha do Be Rich foi alterada"

        client.cookies.clear()
        assert client.post("auth/login", json={"email": "marcelo@example.com", "password": "brand new secret"}).status_code == 200

    def test_wrong_current_password(self, client):
        signup(client)
        response = client.post(
            "auth/password", json={"current_password": "nope-nope", "new_password": "brand new secret"},
            headers=csrf(client),
        )  # fmt: skip
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


class TestPasswordReset:
    def request_reset(self, client, email="marcelo@example.com"):
        return client.post("auth/password-reset/request", json={"email": email})

    def test_full_flow(self, client, db, outbox):
        user_id = signup(client).json()["user"]["id"]
        assert self.request_reset(client, "Marcelo@Example.com").status_code == 202
        token = outbox.last_link_token()
        assert outbox.messages[-1].text.count("http://localhost:3000/reset-password/") == 1

        response = client.post("auth/password-reset/confirm", json={"token": token, "new_password": "reset secret 1"})
        assert response.status_code == 204
        assert session_count(db, user_id) == 0
        assert client.get("auth/me").status_code == 401
        assert client.post("auth/login", json={"email": "marcelo@example.com", "password": "reset secret 1"}).status_code == 200

        again = client.post("auth/password-reset/confirm", json={"token": token, "new_password": "reset secret 2"})
        assert again.status_code == 410
        assert again.json()["error"]["code"] == "TOKEN_INVALID"

    def test_unknown_email_looks_the_same(self, client, outbox):
        response = self.request_reset(client, "nobody@example.com")
        assert response.status_code == 202
        assert outbox.messages == []

    def test_new_request_invalidates_previous_token(self, client, outbox):
        signup(client)
        self.request_reset(client)
        first = outbox.last_link_token()
        self.request_reset(client)
        second = outbox.last_link_token()
        assert client.post("auth/password-reset/confirm", json={"token": first, "new_password": "reset secret 1"}).status_code == 410
        assert client.post("auth/password-reset/confirm", json={"token": second, "new_password": "reset secret 1"}).status_code == 204

    def test_expired_token(self, client, db, outbox):
        signup(client)
        self.request_reset(client)
        token = outbox.last_link_token()
        reset = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token)))
        reset.expires_at = utcnow() - timedelta(seconds=1)
        db.flush()
        assert client.post("auth/password-reset/confirm", json={"token": token, "new_password": "reset secret 1"}).status_code == 410

    def test_weak_new_password(self, client, outbox):
        signup(client)
        self.request_reset(client)
        response = client.post(
            "auth/password-reset/confirm", json={"token": outbox.last_link_token(), "new_password": "short"}
        )
        assert response.status_code == 422
        assert "new_password" in response.json()["error"]["fields"]

    def test_rate_limit_drops_silently(self, client, outbox):
        signup(client)
        for _ in range(4):
            assert self.request_reset(client).status_code == 202
        assert len(outbox.messages) == 3

    def test_email_failure_is_not_revealed(self, client, outbox):
        signup(client)
        outbox.fail = True
        assert self.request_reset(client).status_code == 202
