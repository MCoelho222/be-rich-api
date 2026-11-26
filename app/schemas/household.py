"""Household, members, invitations and profile bodies (specs/api.md §4-§6)."""

import uuid
from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field

from app.domain.enums import Currency, InvitationStatus, Language
from app.schemas.common import OrmModel, Text


class HouseholdOut(OrmModel):
    id: uuid.UUID
    name: str
    default_currency: Currency
    created_at: datetime
    updated_at: datetime


class HouseholdPatch(BaseModel):
    name: Text(60, min_length=1) | None = None
    default_currency: Currency | None = None


class MemberOut(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    is_you: bool


class UserRefOut(BaseModel):
    id: uuid.UUID
    name: str
    is_current_member: bool


class InvitationCreate(BaseModel):
    email: Annotated[EmailStr, Field(max_length=254)]


class InvitationOut(OrmModel):
    id: uuid.UUID
    email: str
    status: InvitationStatus
    invited_by_id: uuid.UUID
    expires_at: datetime
    created_at: datetime


class AddressIn(BaseModel):
    cep: Text(8, min_length=1)
    street: Text(120, min_length=1)
    number: Text(10) | None = None
    complement: Text(60) | None = None
    neighborhood: Text(60) | None = None
    city: Text(60, min_length=1)
    state: Text(2, min_length=2)


class AddressOut(BaseModel):
    cep: str
    street: str
    number: str | None
    complement: str | None
    neighborhood: str | None
    city: str
    state: str


class ProfilePatch(BaseModel):
    """PATCH semantics: omitted fields are unchanged; null clears an optional field."""

    name: Text(100, min_length=1) | None = None
    email: Annotated[EmailStr, Field(max_length=254)] | None = None
    cpf: Text(11) | None = None
    birth_date: date | None = None
    phone: Text(30) | None = None
    address: AddressIn | None = None
    notes: Text(500) | None = None
    language: Language | None = None


class AvatarIn(BaseModel):
    # Generous bound so oversized payloads are rejected before decoding; the real
    # limit on the decoded image is applied by the service.
    image: Annotated[str, Field(max_length=400_000)]


class ProfileOut(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    name: str
    email: str
    cpf: str | None
    birth_date: date | None
    phone: str | None
    address: AddressOut | None
    notes: str | None
    language: Language
    avatar: str | None
    created_at: datetime
    updated_at: datetime
