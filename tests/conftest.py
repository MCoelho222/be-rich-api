import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + "/..")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine, Session
from main import app

from app.models.models import User, Entry
from app.connection_db import get_session
from uuid import uuid4
from datetime import datetime, timezone

# Use SQLite in-memory for tests
TEST_DATABASE_URL = "sqlite://"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # <- keep one connection for the whole process
)

# Dependency override
def get_test_session():
    with Session(test_engine) as session:
        yield session

app.dependency_overrides[get_session] = get_test_session

@pytest.fixture(scope="session")
def create_tables():
    SQLModel.metadata.create_all(test_engine)
    yield
    SQLModel.metadata.drop_all(test_engine)

@pytest.fixture
def client(create_tables):
    return TestClient(app)

@pytest.fixture(autouse=True)
def insert_test_data(create_tables):
    # Insert test data
    with Session(test_engine) as session:
        user = User(id=uuid4(), name="Test User", email="test@example.com", password="testpass")
        entry = Entry(
            id=uuid4(),
            amount=100.0,
            entry_type="Income",  # Use a valid EntryType for your model
            fixed=False,
            payment_method="Pix",  # Use a valid PaymentMethod for your model
            installments=1,
            category="Energy",      # Use a valid Category for your model
            description="Test entry",
            source="Marcelo",           # Use a valid Source for your model
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        session.add(user)
        session.add(entry)
        session.commit()
