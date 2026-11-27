"""transfers

Money moved between accounts and investments; an investment can reach 0 once fully redeemed.

Revision ID: e7a2c9d4b1f3
Revises: db40f5c1b8a6
Create Date: 2026-11-27 21:00:00

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7a2c9d4b1f3"
down_revision: Union[str, None] = "db40f5c1b8a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def END(name: str) -> sa.Enum:
    return sa.Enum(
        "ACCOUNT",
        "INVESTMENT",
        name=name,
        native_enum=False,
        create_constraint=True,
        length=10,
    )


def CURRENCY(name: str) -> sa.Enum:
    return sa.Enum(
        "BRL",
        "USD",
        "EUR",
        name=name,
        native_enum=False,
        create_constraint=True,
        length=3,
    )


def _end_check(end: str) -> str:
    return (
        f"({end}_kind = 'ACCOUNT' AND {end}_account_id IS NOT NULL AND {end}_investment_id IS NULL)"
        f" OR ({end}_kind = 'INVESTMENT' AND {end}_account_id IS NULL AND {end}_label IS NOT NULL)"
    )


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_investments_amount_positive"), "investments", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_investments_amount_positive"), "investments", "amount >= 0"
    )

    op.create_table(
        "transfers",
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=True),
        sa.Column("from_kind", END("from_kind"), nullable=False),
        sa.Column("from_account_id", sa.Uuid(), nullable=True),
        sa.Column("from_investment_id", sa.Uuid(), nullable=True),
        sa.Column("from_label", sa.String(length=84), nullable=True),
        sa.Column("amount_sent", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency_sent", CURRENCY("currency_sent"), nullable=False),
        sa.Column("to_kind", END("to_kind"), nullable=False),
        sa.Column("to_account_id", sa.Uuid(), nullable=True),
        sa.Column("to_investment_id", sa.Uuid(), nullable=True),
        sa.Column("to_label", sa.String(length=84), nullable=True),
        sa.Column("amount_received", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency_received", CURRENCY("currency_received"), nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amount_sent > 0", name=op.f("ck_transfers_amount_sent_positive")
        ),
        sa.CheckConstraint(
            "amount_received > 0", name=op.f("ck_transfers_amount_received_positive")
        ),
        sa.CheckConstraint(
            "from_account_id IS DISTINCT FROM to_account_id OR from_account_id IS NULL",
            name=op.f("ck_transfers_distinct_accounts"),
        ),
        sa.CheckConstraint(
            "from_investment_id IS DISTINCT FROM to_investment_id OR from_investment_id IS NULL",
            name=op.f("ck_transfers_distinct_investments"),
        ),
        sa.CheckConstraint(
            _end_check("from"), name=op.f("ck_transfers_from_matches_kind")
        ),
        sa.CheckConstraint(_end_check("to"), name=op.f("ck_transfers_to_matches_kind")),
        sa.ForeignKeyConstraint(
            ["household_id"],
            ["households.id"],
            name=op.f("fk_transfers_household_id_households"),
        ),
        sa.ForeignKeyConstraint(
            ["from_account_id"],
            ["accounts.id"],
            name=op.f("fk_transfers_from_account_id_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["to_account_id"],
            ["accounts.id"],
            name=op.f("fk_transfers_to_account_id_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["from_investment_id"],
            ["investments.id"],
            name=op.f("fk_transfers_from_investment_id_investments"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["to_investment_id"],
            ["investments.id"],
            name=op.f("fk_transfers_to_investment_id_investments"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_transfers_created_by_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transfers")),
    )
    op.create_index(
        "ix_transfers_household_date",
        "transfers",
        ["household_id", "date"],
        unique=False,
    )
    for column in (
        "from_account_id",
        "to_account_id",
        "from_investment_id",
        "to_investment_id",
    ):
        op.create_index(
            op.f(f"ix_transfers_{column}"), "transfers", [column], unique=False
        )


def downgrade() -> None:
    for column in (
        "from_account_id",
        "to_account_id",
        "from_investment_id",
        "to_investment_id",
    ):
        op.drop_index(op.f(f"ix_transfers_{column}"), table_name="transfers")
    op.drop_index("ix_transfers_household_date", table_name="transfers")
    op.drop_table("transfers")
    op.drop_constraint(
        op.f("ck_investments_amount_positive"), "investments", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_investments_amount_positive"), "investments", "amount > 0"
    )
