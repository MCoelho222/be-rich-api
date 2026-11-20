"""Shared schema helpers."""

import re
from decimal import Decimal
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, PlainSerializer, StringConstraints

from app.domain.money import to_money

T = TypeVar("T")

_MONEY_PATTERN = re.compile(r"-?\d{1,10}(\.\d{1,2})?")


def _parse_money(value: Any) -> Decimal:
    """Money travels as a decimal string ("1234.50"), never a JSON number (specs/api.md §1.1)."""
    if not isinstance(value, str):
        raise ValueError('Must be a decimal string, e.g. "1234.50"')
    value = value.strip()
    if not _MONEY_PATTERN.fullmatch(value):
        raise ValueError('Must be a decimal string with up to 2 decimal places, e.g. "1234.50"')
    return to_money(value)


def _format_money(value: Decimal) -> str:
    return f"{value:.2f}"


MoneyIn = Annotated[Decimal, BeforeValidator(_parse_money)]
MoneyOut = Annotated[Decimal, PlainSerializer(_format_money, return_type=str)]


def Text(max_length: int, min_length: int = 0):  # noqa: N802 - reads like a type
    """A trimmed string. Empty strings are turned into None by `blank_to_none`."""
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=min_length, max_length=max_length)]


def blank_to_none(value: str | None) -> str | None:
    return value or None


class Items(BaseModel, Generic[T]):
    """`{"items": [...]}` for unpaginated reference lists (specs/api.md §3)."""

    items: list[T]


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)
