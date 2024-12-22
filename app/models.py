from datetime import datetime
from enum import Enum
from sqlmodel import SQLModel, Field
from typing import Optional

class PaymentMethod(str, Enum):
    NU = "NU"
    PORTO = "PORTO"
    PIX = "PIX"

class Category(str, Enum):
    APPS = "APPS"
    BILLS = "BILLS"
    CAR_REVIEW = "CAR_REVIEW"
    CAR_TAX = "CAR_TAX"
    CONECTCAR = "CONECTCAR"
    EDUCATION = "EDUCATION"
    ENTERTAINMENT = "ENTERTAINMENT"
    FUEL = "FUEL"
    HEALTH = "HEALTH"
    MARKET = "MARKET"
    PHARMACY = "PHARMACY"
    PHONE = "PHONE"
    OTHER = "OTHER"
    RENT = "RENT"
    SHOPPING = "SHOPPING"

class CardOwner(str, Enum):
    MARCELO = "MARCELO"
    MARILIA = "MARILIA"

class IncomeSource(str, Enum):
    MARCELO = "MARCELO"
    MARILIA = "MARILIA"
    OTHER = "OTHER"

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
    card_owner: CardOwner

class Income(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source: IncomeSource
    amount: float
    fixed: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)