from enum import Enum

class PaymentMethod(str, Enum):
    NU = "NU"
    PORTO = "Porto"
    SANTANDER = "Santander"
    PIX = "Pix"

class Category(str, Enum):
    APPS = "Apps"
    HOUSE = "House"
    GAS = "Gas"
    INTERNET = "Internet"
    ENERGY = "Energy"
    HOUSE_INSTALLMENT = "House Installment"
    CAR = "Car"
    EDUCATION = "Education"
    ENTERTAINMENT = "Entertainment"
    HEALTH = "Health"
    SUPERMARKET = "Supermarket"
    CLOTHES = "Clothes"
    PHARMACY = "Pharmacy"
    PHONE = "Phone"
    RENT = "Rent"
    GIFT = "Gift"
    OTHER = "Other"
    KIDS = "Kids"

class Source(str, Enum):
    MARCELO = "Marcelo"
    MARILIA = "Marilia"
    OTHER = "Other"

class EntryType(str, Enum):
    INCOME = "Income"
    EXPENSE = "Expense"
