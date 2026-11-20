"""The user's own profile (specs/schemas.md §5)."""

from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import ApiError, validation_error
from app.domain.br import UFS, is_valid_cep, is_valid_cpf, normalize_phone
from app.models import User
from app.schemas.common import blank_to_none
from app.schemas.household import AddressOut, ProfileOut, ProfilePatch
from app.services.auth import normalize_email

ADDRESS_COLUMNS = ("cep", "street", "number", "complement", "neighborhood", "city", "state")
MIN_BIRTH_DATE = date(1900, 1, 2)


def to_out(user: User) -> ProfileOut:
    address = None
    if user.address_cep is not None:
        address = AddressOut(**{c: getattr(user, f"address_{c}") for c in ADDRESS_COLUMNS})
    return ProfileOut(
        id=user.id, household_id=user.household_id, name=user.name, email=user.email, cpf=user.cpf,
        birth_date=user.birth_date, phone=user.phone, address=address, notes=user.notes, language=user.language,
        created_at=user.created_at, updated_at=user.updated_at,
    )  # fmt: skip


def update_profile(db: Session, user: User, patch: ProfilePatch, today: date) -> None:
    sent = patch.model_fields_set
    errors: dict[str, list[str]] = {}

    def fail(field: str, message: str) -> None:
        errors.setdefault(field, []).append(message)

    for required in ("name", "email", "language"):
        if required in sent and getattr(patch, required) is None:
            fail(required, "Can't be empty")

    if "cpf" in sent and (cpf := blank_to_none(patch.cpf)) is not None and not is_valid_cpf(cpf):
        fail("cpf", "Invalid CPF")
    if "birth_date" in sent and patch.birth_date is not None:
        if not MIN_BIRTH_DATE <= patch.birth_date < today:
            fail("birth_date", "Must be in the past and after 01/01/1900")
    phone = None
    if "phone" in sent and (raw_phone := blank_to_none(patch.phone)) is not None:
        phone = normalize_phone(raw_phone)
        if phone is None:
            fail("phone", "Invalid phone number")
    if "address" in sent and patch.address is not None:
        if not is_valid_cep(patch.address.cep):
            fail("address.cep", "Must be 8 digits")
        if patch.address.state.upper() not in UFS:
            fail("address.state", "Invalid state")
    if errors:
        raise validation_error(errors)

    if "name" in sent:
        user.name = patch.name
    if "language" in sent:
        user.language = patch.language
    if "email" in sent:
        email = normalize_email(str(patch.email))
        if email != user.email and db.scalar(select(User.id).where(User.email == email)) is not None:
            raise ApiError(409, "CONFLICT", "Email already registered.", fields={"email": ["Email already registered"]})
        user.email = email
    if "cpf" in sent:
        user.cpf = blank_to_none(patch.cpf)
    if "birth_date" in sent:
        user.birth_date = patch.birth_date
    if "phone" in sent:
        user.phone = phone
    if "address" in sent:
        address = patch.address
        for column in ADDRESS_COLUMNS:
            value = None if address is None else blank_to_none(getattr(address, column))
            if column == "state" and value:
                value = value.upper()
            setattr(user, f"address_{column}", value)
    if "notes" in sent:
        user.notes = blank_to_none(patch.notes)

    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError as exc:
        constraint = str(exc.orig)
        field = "cpf" if "cpf" in constraint else "email"
        raise ApiError(409, "CONFLICT", f"This {field} is already registered.", fields={field: ["Already registered"]}) from exc
