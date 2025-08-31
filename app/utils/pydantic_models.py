from pydantic import BaseModel
from datetime import datetime
from uuid import UUID
from app.models.models import PaymentMethod, Category, Source, EntryType

class UserCreate(BaseModel):
    name: str
    email: str
    password: str

class UserRead(BaseModel):
    id: UUID
    name: str
    email: str

class EntryCreate(BaseModel):
    amount: float
    entry_type: EntryType
    fixed: bool = False
    installments: int = 1
    payment_method: PaymentMethod
    category: Category
    description: str = None
    source: Source
    created_at: datetime

class EntryRead(BaseModel):
    id: UUID
    amount: float
    entry_type: EntryType
    fixed: bool = False
    installments: int = 1
    payment_method: PaymentMethod
    category: Category
    description: str = None
    source: Source
    created_at: datetime