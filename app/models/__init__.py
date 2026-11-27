"""ORM models (specs/schemas.md and specs/auth.md §2).

Importing this package registers every table on `Base.metadata`.
"""

from app.models.auth import PasswordResetToken, RateLimitHit, Session
from app.models.entries import Expense, Income
from app.models.household import Household, Invitation, User
from app.models.investment import Investment
from app.models.recurrence import Recurrence
from app.models.reference import Account, Card, Category
from app.models.system import ExchangeRate, Holiday
from app.models.transfer import Transfer

__all__ = [
    "Account",
    "Card",
    "Category",
    "ExchangeRate",
    "Expense",
    "Holiday",
    "Household",
    "Income",
    "Invitation",
    "Investment",
    "PasswordResetToken",
    "RateLimitHit",
    "Recurrence",
    "Session",
    "Transfer",
    "User",
]
