"""Shared schema helpers."""

from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, StringConstraints

T = TypeVar("T")


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
