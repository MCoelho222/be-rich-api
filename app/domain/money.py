"""Money handling (specs/schemas.md §1 and §10.1).

Money is always a Decimal with 2 decimal places, never a float.
"""

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("9999999999.99")  # decimal(12,2)


def to_money(value: Decimal | str | int) -> Decimal:
    """Parse an exact money value. Rejects floats and more than 2 decimal places."""
    if isinstance(value, float):
        raise TypeError("money must not be a float; pass a str or Decimal")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"invalid money value: {value!r}") from exc
    if not amount.is_finite():
        raise ValueError("money must be a finite number")
    if amount != amount.quantize(CENT):
        raise ValueError("money must have at most 2 decimal places")
    if abs(amount) > MAX_AMOUNT:
        raise ValueError("money exceeds the maximum of 9999999999.99")
    return amount.quantize(CENT)


def round_money(value: Decimal) -> Decimal:
    """Round a full-precision result (e.g. a converted sum) to cents, once, at the end."""
    return value.quantize(CENT, rounding=ROUND_HALF_EVEN)


def split_amount(total: Decimal, parts: int) -> list[Decimal]:
    """Split `total` into `parts` installments (§10.1 rule 3).

    Each part is total / parts rounded down to the cent; the leftover cents go to
    the first installment, so the parts always sum to the total.
    Example: 100.00 / 3 -> [33.34, 33.33, 33.33].
    """
    total = to_money(total)
    if parts < 1:
        raise ValueError("parts must be at least 1")
    if total <= 0:
        raise ValueError("total must be greater than zero")
    cents = int(total * 100)
    if cents < parts:
        raise ValueError("total is too small to split: every installment must be at least 0.01")
    base, remainder = divmod(cents, parts)
    amounts = [Decimal(base) / 100] * parts
    amounts[0] = Decimal(base + remainder) / 100
    return [a.quantize(CENT) for a in amounts]
