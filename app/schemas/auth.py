"""Request and response bodies for /auth (specs/auth.md §4)."""

import uuid
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints

from app.domain.enums import Currency

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# Generous upper bound so oversized payloads never reach the password hasher;
# the real 8-128 rule is applied by the service with a friendly message.
RawPassword = Annotated[str, Field(max_length=1024)]
RawEmail = Annotated[str, Field(max_length=320)]


class SignupIn(BaseModel):
    name: Name
    email: Annotated[EmailStr, Field(max_length=254)]
    password: RawPassword
    invitation_token: str | None = None


class LoginIn(BaseModel):
    email: RawEmail
    password: RawPassword


class ChangePasswordIn(BaseModel):
    current_password: RawPassword
    new_password: RawPassword


class PasswordResetRequestIn(BaseModel):
    email: RawEmail


class PasswordResetConfirmIn(BaseModel):
    token: Annotated[str, Field(max_length=200)]
    new_password: RawPassword


class MeUser(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    household_id: uuid.UUID


class MeHousehold(BaseModel):
    id: uuid.UUID
    name: str
    default_currency: Currency


class MeOut(BaseModel):
    user: MeUser
    household: MeHousehold


class InvitationLookupOut(BaseModel):
    household_name: str
    email: str
    invited_by_name: str
