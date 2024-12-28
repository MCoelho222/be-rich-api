from enum import Enum

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
