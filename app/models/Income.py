from datetime import datetime, timezone
from sqlmodel import SQLModel, Field
from uuid import UUID, uuid4
from app.utils.models_helpers import Source


class Income(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    amount: float
    installments: str | None = Field(default=None)
    description: str | None = Field(default=None)
    source: Source
    created_at: datetime
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class IncomeFixed(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    amount: float
    installments: str | None = Field(default=None)
    description: str | None = Field(default=None)
    source: Source
    created_at: datetime
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    
