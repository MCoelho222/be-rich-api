"""Enums shared by the domain rules (specs/schemas.md §3)."""

from enum import StrEnum


class PaymentMethod(StrEnum):
    CASH = "CASH"
    PIX = "PIX"
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    BOLETO = "BOLETO"
    BANK_TRANSFER = "BANK_TRANSFER"


class Language(StrEnum):
    """UI language, also used for seed data such as default category names."""

    EN = "en"
    PT = "pt"


class Currency(StrEnum):
    BRL = "BRL"
    USD = "USD"
    EUR = "EUR"


class AccountType(StrEnum):
    BANK = "BANK"
    CASH = "CASH"


class CardType(StrEnum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
    CREDIT_DEBIT = "CREDIT_DEBIT"

    def supports(self, method: PaymentMethod) -> bool:
        if method is PaymentMethod.CREDIT:
            return self in (CardType.CREDIT, CardType.CREDIT_DEBIT)
        if method is PaymentMethod.DEBIT:
            return self in (CardType.DEBIT, CardType.CREDIT_DEBIT)
        return False

    @property
    def has_credit(self) -> bool:
        return self.supports(PaymentMethod.CREDIT)


class EntryType(StrEnum):
    EXPENSE = "EXPENSE"
    INCOME = "INCOME"


class EditScope(StrEnum):
    THIS = "THIS"
    THIS_AND_FOLLOWING = "THIS_AND_FOLLOWING"
    ALL = "ALL"


class InvitationStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class OccurrenceStatus(StrEnum):
    REGISTERED = "REGISTERED"
    PENDING = "PENDING"
    OVERDUE = "OVERDUE"
    FUTURE = "FUTURE"
    SKIPPED = "SKIPPED"


CARD_METHODS = frozenset({PaymentMethod.CREDIT, PaymentMethod.DEBIT})
