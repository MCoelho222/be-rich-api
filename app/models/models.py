from datetime import datetime, timezone
from sqlmodel import SQLModel, Field
from typing import Optional
from uuid import UUID, uuid4
from app.utils.models_helpers import Category, Source, PaymentMethod, EntryType


class User(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    email: str
    password: str


class Entry(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    amount: float
    entry_type: EntryType
    fixed: bool = Field(default=False)
    payment_method: PaymentMethod
    installments: int = Field(default=1)
    category: Category
    description: Optional[str] = Field(default=None)
    source: Source
    created_at: datetime
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
