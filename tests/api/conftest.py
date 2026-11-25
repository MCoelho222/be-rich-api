"""API test fixtures: a TestClient bound to the per-test database session."""

import re
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.email import EmailMessage, get_email_sender
from main import create_app

PASSWORD = "correct horse battery"


class Outbox:
    """Captures emails instead of sending them."""

    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []
        self.fail = False

    def send(self, message: EmailMessage) -> None:
        from app.services.email import EmailError

        if self.fail:
            raise EmailError("provider down")
        self.messages.append(message)

    def last_link_token(self) -> str:
        match = re.search(r"/(?:reset-password|invite)/([\w-]+)", self.messages[-1].text)
        assert match, self.messages[-1].text
        return match.group(1)


@pytest.fixture
def outbox() -> Outbox:
    return Outbox()


@pytest.fixture
def app(db: Session, outbox: Outbox):
    application = create_app()

    def override_db() -> Iterator[Session]:
        try:
            yield db
        except Exception:
            db.rollback()
            raise

    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[get_email_sender] = lambda: outbox
    return application


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app, base_url="http://testserver/api/v1/")


def csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("brs_csrf", "")}


def signup(client: TestClient, email: str = "marcelo@example.com", name: str = "Marcelo Coelho", **extra):
    return client.post("auth/signup", json={"name": name, "email": email, "password": PASSWORD, **extra})
