"""investments

Investments held by a household; the ones marked include_in_balance add to the total balance.

Revision ID: db40f5c1b8a6
Revises: d5f1a7c3e208
Create Date: 2026-11-26 21:23:25.364525

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db40f5c1b8a6'
down_revision: Union[str, None] = 'd5f1a7c3e208'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('investments',
    sa.Column('household_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=40), nullable=True),
    sa.Column('bank', sa.String(length=40), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('currency', sa.Enum('BRL', 'USD', 'EUR', name='currency', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('invested_on', sa.Date(), nullable=False),
    sa.Column('liquidity', sa.Enum('DAILY', 'MATURITY', name='liquidity', native_enum=False, create_constraint=True), nullable=False),
    sa.Column('maturity_date', sa.Date(), nullable=True),
    sa.Column('include_in_balance', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(liquidity = 'DAILY' AND maturity_date IS NULL) OR (liquidity = 'MATURITY' AND maturity_date IS NOT NULL AND maturity_date > invested_on)", name=op.f('ck_investments_maturity_matches_liquidity')),
    sa.CheckConstraint('amount > 0', name=op.f('ck_investments_amount_positive')),
    sa.ForeignKeyConstraint(['household_id'], ['households.id'], name=op.f('fk_investments_household_id_households')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_investments'))
    )
    op.create_index(op.f('ix_investments_household_id'), 'investments', ['household_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_investments_household_id'), table_name='investments')
    op.drop_table('investments')
