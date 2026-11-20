"""Brazilian document and address validators (specs/schemas.md §5)."""

import re

import phonenumbers

UFS = frozenset(
    "AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split()
)


def is_valid_cpf(cpf: str) -> bool:
    """11 digits with valid check digits; sequences of one repeated digit are rejected."""
    if not re.fullmatch(r"\d{11}", cpf) or len(set(cpf)) == 1:
        return False
    for length in (9, 10):
        total = sum(int(cpf[i]) * (length + 1 - i) for i in range(length))
        if (total * 10) % 11 % 10 != int(cpf[length]):
            return False
    return True


def is_valid_cep(cep: str) -> bool:
    return re.fullmatch(r"\d{8}", cep) is not None


def normalize_phone(phone: str) -> str | None:
    """The E.164 form of a valid international number, or None if it is not valid."""
    if not phone.startswith("+"):
        return None
    try:
        parsed = phonenumbers.parse(phone, None)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
