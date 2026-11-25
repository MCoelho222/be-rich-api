"""Household, User and Invitation (specs/schemas.md §4-§6)."""

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk, str_enum
from app.domain.enums import Currency, InvitationStatus, Language


class Household(UUIDPk, Timestamps, Base):
    __tablename__ = "households"

    name: Mapped[str] = mapped_column(String(60))
    default_currency: Mapped[Currency] = mapped_column(
        str_enum(Currency, "currency"), default=Currency.BRL
    )


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint(r"cpf ~ '^[0-9]{11}$'", name="cpf_digits"),
        CheckConstraint(r"phone ~ '^\+[1-9][0-9]{7,14}$'", name="phone_e164"),
        CheckConstraint(r"address_cep ~ '^[0-9]{8}$'", name="cep_digits"),
        CheckConstraint(r"address_state ~ '^[A-Z]{2}$'", name="state_uf"),
        CheckConstraint(
            "(address_cep IS NULL AND address_street IS NULL AND address_number IS NULL"
            " AND address_complement IS NULL AND address_neighborhood IS NULL"
            " AND address_city IS NULL AND address_state IS NULL)"
            " OR (address_cep IS NOT NULL AND address_street IS NOT NULL"
            " AND address_city IS NOT NULL AND address_state IS NOT NULL)",
            name="address_complete",
        ),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    language: Mapped[Language] = mapped_column(str_enum(Language, "language"), default=Language.EN)
    cpf: Mapped[str | None] = mapped_column(String(11), unique=True)
    birth_date: Mapped[date | None] = mapped_column(Date)
    phone: Mapped[str | None] = mapped_column(String(16))
    # Address (§5.1), embedded as columns
    address_cep: Mapped[str | None] = mapped_column(String(8))
    address_street: Mapped[str | None] = mapped_column(String(120))
    address_number: Mapped[str | None] = mapped_column(String(10))
    address_complement: Mapped[str | None] = mapped_column(String(60))
    address_neighborhood: Mapped[str | None] = mapped_column(String(60))
    address_city: Mapped[str | None] = mapped_column(String(60))
    address_state: Mapped[str | None] = mapped_column(String(2))
    notes: Mapped[str | None] = mapped_column(String(500))


class Invitation(UUIDPk, Base):
    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        # Only one PENDING invitation per email per household (§6.1 rule 3)
        Index(
            "uq_invitations_pending_email",
            "household_id",
            "email",
            unique=True,
            postgresql_where=text("status = 'PENDING'"),
        ),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("households.id"), index=True)
    email: Mapped[str] = mapped_column(String(254))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[InvitationStatus] = mapped_column(
        str_enum(InvitationStatus, "invitation_status"), default=InvitationStatus.PENDING
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
