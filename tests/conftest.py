"""Shared fixtures.

Database tests run against a real Postgres (the schema uses decimal, array and
regex CHECK constraints). Start it with:

    docker compose --profile test up -d be_rich_test_db

The schema is rebuilt once per run with the Alembic migrations (which also tests
them), and every test runs inside a transaction that is rolled back.
Domain tests do not request these fixtures and run without a database.
"""

import os
from collections.abc import Iterator

import pytest

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://berich:berich@localhost:5433/berich_test"
)
# Must be set before the app reads its settings.
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ENV"] = "test"

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    eng = create_engine(TEST_DATABASE_URL)
    try:
        with eng.connect() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
            conn.commit()
    except OperationalError:
        pytest.skip(
            "Test database unavailable. Run: docker compose --profile test up -d be_rich_test_db"
        )
    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "alembic"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after the test, even if it commits."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
