from datetime import datetime
from sqlmodel import SQLModel, Field
from typing import Optional
from app.models_helpers import CardOwner, Category, IncomeSource, PaymentMethod

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str
    password: str

class Expense(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    amount: float
    fixed: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    payment_method: PaymentMethod
    category: Category
    installments: int = Field(default=1)
    description: Optional[str] = Field(default=None)
    card_owner: CardOwner

class Income(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source: IncomeSource
    amount: float
    fixed: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    description: Optional[str] = Field(default=None)