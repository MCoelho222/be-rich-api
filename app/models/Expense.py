from datetime import datetime, timezone
from sqlmodel import SQLModel, Field
from uuid import UUID, uuid4
from app.utils.models_helpers import Category, Source, PaymentMethod


class Expense(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    amount: float
    payment_method: PaymentMethod | None
    installment: str | None = Field(default=None)
    category: Category | None = Field(default=None)
    description: str | None = Field(default=None)
    source: Source
    created_at: datetime
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExpenseFixed(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    amount: float
    payment_method: PaymentMethod | None
    installment: str | None = Field(default=None)
    category: Category | None = Field(default=None)
    description: str | None = Field(default=None)
    source: Source
    created_at: datetime
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))