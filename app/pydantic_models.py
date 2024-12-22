from pydantic import BaseModel
from datetime import datetime
from app.models import PaymentMethod, Category, CardOwner, IncomeSource

class UserCreate(BaseModel):
    name: str
    email: str
    password: str

class UserRead(BaseModel):
    id: int
    name: str
    email: str

class ExpenseCreate(BaseModel):
    amount: float
    fixed: bool = False
    payment_method: PaymentMethod
    category: Category
    installments: int = 1
    card_owner: CardOwner

class ExpenseRead(BaseModel):
    id: int
    amount: float
    fixed: bool
    created_at: datetime
    payment_method: PaymentMethod
    category: Category
    installments: int
    card_owner: CardOwner

class IncomeCreate(BaseModel):
    source: IncomeSource
    amount: float
    fixed: bool = True

class IncomeRead(BaseModel):
    id: int
    source: IncomeSource
    amount: float
    fixed: bool
    created_at: datetime