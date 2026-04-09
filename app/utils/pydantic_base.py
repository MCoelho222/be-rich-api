from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from app.utils.models_helpers import Source


class EntryBase(BaseModel):
    amount: float
    installment: str | None = None
    description: str | None = None
    source: Source
    created_at: datetime


class EntryReadBase(EntryBase):
    id: UUID
    updated_at: datetime
