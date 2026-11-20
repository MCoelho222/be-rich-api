"""Database-level guarantees: seed data and the constraints from specs/schemas.md."""

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, StatementError

from app.db.session import get_db
from app.domain.enums import CardType, Currency, EntryType, InvitationStatus, PaymentMethod
from app.models import Account, Category, Invitation, Recurrence
from app.services.households import DEFAULT_EXPENSE_CATEGORIES
from main import app
from tests.db.factories import (
    TODAY,
    cash_account,
    expense_category,
    make_bank_account,
    make_card,
    make_expense,
    make_household,
    make_user,
)


def rejects(db, build, match: str):
    """Assert the database rejects what `build` adds, citing `match` (a constraint
    or column name), so a test cannot pass because of an unrelated error."""
    with pytest.raises((IntegrityError, StatementError), match=match):
        with db.begin_nested():
            build()
            db.flush()


class TestHouseholdSeed:
    def test_new_household_gets_categories_and_cash_account(self, db):
        household = make_household(db, "Marcelo Coelho")
        assert household.name == "Marcelo's household"
        assert household.default_currency is Currency.BRL

        names = db.scalars(select(Category.name).where(Category.household_id == household.id)).all()
        assert sorted(names) == sorted(DEFAULT_EXPENSE_CATEGORIES)
        assert len(names) == 25

        cash = cash_account(db, household)
        assert (cash.name, cash.opening_balance, cash.opening_balance_date) == ("Cash", Decimal("0.00"), TODAY)

    def test_households_are_independent(self, db):
        a, b = make_household(db), make_household(db)
        assert expense_category(db, a).id != expense_category(db, b).id


class TestUserConstraints:
    def test_email_unique_and_lowercase(self, db):
        h = make_household(db)
        make_user(db, h, email="m@example.com")
        rejects(db, lambda: make_user(db, h, email="m@example.com"), "uq_users_email")
        rejects(db, lambda: make_user(db, h, email="Upper@example.com"), "ck_users_email_lowercase")

    @pytest.mark.parametrize(
        "fields,constraint",
        [
            ({"cpf": "123456789-0"}, "ck_users_cpf_digits"),  # 11 chars, not all digits
            ({"phone": "48999999999"}, "ck_users_phone_e164"),
            ({"address_cep": "88303575"}, "ck_users_address_complete"),  # partial address
            (
                {"address_cep": "8830357", "address_street": "R", "address_city": "C", "address_state": "SC"},
                "ck_users_cep_digits",
            ),
        ],
    )
    def test_invalid_personal_fields(self, db, fields, constraint):
        h = make_household(db)
        rejects(db, lambda: make_user(db, h, **fields), constraint)

    def test_valid_personal_fields(self, db):
        h = make_household(db)
        user = make_user(
            db, h, cpf="12345678909", phone="+5548999999999", address_cep="88303575",
            address_street="Rua X", address_city="Itajaí", address_state="SC",
        )  # fmt: skip
        assert user.id


class TestReferenceConstraints:
    def test_account_names_unique_case_insensitive(self, db):
        h = make_household(db)
        make_bank_account(db, h, "Nubank")
        rejects(db, lambda: make_bank_account(db, h, "NUBANK"), "uq_accounts_household_name")
        make_bank_account(db, make_household(db), "Nubank")  # other household: fine

    def test_category_unique_per_type(self, db):
        h = make_household(db)
        rejects(
            db,
            lambda: db.add(Category(household_id=h.id, type=EntryType.EXPENSE, name="food")),
            "uq_categories_household_type_name",
        )
        db.add(Category(household_id=h.id, type=EntryType.INCOME, name="Food"))
        db.flush()

    @pytest.mark.parametrize(
        "fields,constraint",
        [
            ({"type": CardType.DEBIT}, "ck_cards_credit_days"),  # debit with days
            ({"type": CardType.CREDIT, "best_buy_day": None}, "ck_cards_credit_days"),
            ({"alias": "Two words"}, "ck_cards_alias_single_word"),
            ({"due_day": 32}, "ck_cards_due_day_range"),
            ({"last_four": "12a4"}, "ck_cards_last_four_digits"),
        ],
    )
    def test_invalid_cards(self, db, fields, constraint):
        h = make_household(db)
        u, acc = make_user(db, h), make_bank_account(db, h)
        rejects(db, lambda: make_card(db, h, u, acc, **fields), constraint)

    def test_card_alias_unique_case_insensitive_and_debit_without_days(self, db):
        h = make_household(db)
        u, acc = make_user(db, h), make_bank_account(db, h)
        make_card(db, h, u, acc, alias="Porto")
        rejects(db, lambda: make_card(db, h, u, acc, alias="porto"), "uq_cards_household_alias")
        make_card(db, h, u, acc, alias="NuDebit", type=CardType.DEBIT, best_buy_day=None, due_day=None)

    def test_unknown_enum_value_rejected(self, db):
        h = make_household(db)
        rejects(
            db,
            lambda: db.add(
                Account(household_id=h.id, type="SAVINGS", name="X", currency=Currency.BRL,
                        opening_balance_date=TODAY)
            ),
            "SAVINGS",
        )  # fmt: skip


class TestEntryConstraints:
    def test_money_round_trips_exactly(self, db):
        h = make_household(db)
        e = make_expense(db, h, make_user(db, h), amount=Decimal("1234567890.12"))
        db.expire(e)
        assert e.amount == Decimal("1234567890.12")

    @pytest.mark.parametrize(
        "fields,constraint",
        [
            ({"amount": Decimal("0.00")}, "ck_expenses_amount_positive"),
            ({"installment_total": 3, "installment_number": 1}, "ck_expenses_installment_group"),
            ({"installment_group_id": uuid.uuid4()}, "ck_expenses_installment_group"),
            (
                {"installment_total": 2, "installment_number": 3, "installment_group_id": uuid.uuid4()},
                "ck_expenses_installment_number_range",
            ),
            ({"installment_total": 61, "installment_group_id": uuid.uuid4()}, "ck_expenses_installment_total_range"),
            ({"occurrence_date": TODAY}, "ck_expenses_occurrence_pair"),
        ],
    )
    def test_invalid_rows(self, db, fields, constraint):
        h = make_household(db)
        u = make_user(db, h)
        rejects(db, lambda: make_expense(db, h, u, **fields), constraint)

    def test_card_required_exactly_for_card_methods(self, db):
        h = make_household(db)
        u, acc = make_user(db, h), make_bank_account(db, h)
        card = make_card(db, h, u, acc)
        rejects(
            db,
            lambda: make_expense(db, h, u, payment_method=PaymentMethod.CREDIT, account_id=acc.id),
            "ck_expenses_card_matches_method",
        )
        rejects(
            db,
            lambda: make_expense(db, h, u, payment_method=PaymentMethod.PIX, card_id=card.id, account_id=acc.id),
            "ck_expenses_card_matches_method",
        )
        make_expense(db, h, u, payment_method=PaymentMethod.CREDIT, card_id=card.id, account_id=acc.id)

    def test_debit_cannot_have_installments(self, db):
        h = make_household(db)
        u, acc = make_user(db, h), make_bank_account(db, h)
        card = make_card(db, h, u, acc, type=CardType.DEBIT, best_buy_day=None, due_day=None)
        rejects(
            db,
            lambda: make_expense(
                db, h, u, payment_method=PaymentMethod.DEBIT, card_id=card.id, account_id=acc.id,
                installment_total=2, installment_group_id=uuid.uuid4(),
            ),
            "ck_expenses_debit_single_installment",
        )  # fmt: skip

    def test_occurrence_registered_once(self, db):
        h = make_household(db)
        u = make_user(db, h)
        rec = Recurrence(
            household_id=h.id, type=EntryType.EXPENSE, person_id=u.id, amount=Decimal("100.00"),
            currency=Currency.BRL, payment_method=PaymentMethod.CASH,
            account_id=cash_account(db, h).id, category_id=expense_category(db, h).id,
            day_of_month=5, start_date=TODAY, created_by_id=u.id,
        )  # fmt: skip
        db.add(rec)
        db.flush()
        assert rec.skipped_dates == []
        occ = TODAY + timedelta(days=15)
        make_expense(db, h, u, recurrence_id=rec.id, occurrence_date=occ)
        rejects(
            db,
            lambda: make_expense(db, h, u, recurrence_id=rec.id, occurrence_date=occ),
            "uq_expenses_recurrence_occurrence",
        )


class TestInvitations:
    def test_one_pending_invitation_per_email(self, db):
        h = make_household(db)
        u = make_user(db, h)

        def invite(status=InvitationStatus.PENDING):
            db.add(
                Invitation(
                    household_id=h.id, email="ana@example.com", token_hash=uuid.uuid4().hex,
                    invited_by_id=u.id, status=status, expires_at=u.created_at + timedelta(days=7),
                )
            )  # fmt: skip
            db.flush()

        invite(InvitationStatus.REVOKED)
        invite()
        rejects(db, invite, "uq_invitations_pending_email")


def test_health_endpoint(db):
    app.dependency_overrides[get_db] = lambda: db
    try:
        response = TestClient(app).get("/api/v1/health")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}
