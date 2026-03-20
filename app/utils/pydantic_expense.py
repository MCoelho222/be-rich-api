from app.utils.models_helpers import PaymentMethod, Category
from app.utils.pydantic_base import EntryBase, EntryReadBase


class ExpenseCreate(EntryBase):
    payment_method: PaymentMethod | None = None
    category: Category | None = None


class ExpenseRead(EntryReadBase):
    payment_method: PaymentMethod | None = None
    category: Category | None = None