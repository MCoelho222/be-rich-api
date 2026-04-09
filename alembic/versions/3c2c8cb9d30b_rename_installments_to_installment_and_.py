"""rename installments to installment and change to string

Revision ID: 3c2c8cb9d30b
Revises: af8b6fa7f6e1
Create Date: 2026-04-09 00:34:44.009833

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '3c2c8cb9d30b'
down_revision: Union[str, None] = 'af8b6fa7f6e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename column and change type for expense table
    op.alter_column('expense', 'installments',
                    new_column_name='installment',
                    type_=sa.String(),
                    existing_type=sa.Integer(),
                    nullable=True)
    
    # Rename column and change type for expensefixed table
    op.alter_column('expensefixed', 'installments',
                    new_column_name='installment',
                    type_=sa.String(),
                    existing_type=sa.Integer(),
                    nullable=True)
    
    # Rename column and change type for income table
    op.alter_column('income', 'installments',
                    new_column_name='installment',
                    type_=sa.String(),
                    existing_type=sa.Integer(),
                    nullable=True)
    
    # Rename column and change type for incomefixed table
    op.alter_column('incomefixed', 'installments',
                    new_column_name='installment',
                    type_=sa.String(),
                    existing_type=sa.Integer(),
                    nullable=True)


def downgrade() -> None:
    # Reverse changes for incomefixed table
    op.alter_column('incomefixed', 'installment',
                    new_column_name='installments',
                    type_=sa.Integer(),
                    existing_type=sa.String(),
                    nullable=True)
    
    # Reverse changes for income table
    op.alter_column('income', 'installment',
                    new_column_name='installments',
                    type_=sa.Integer(),
                    existing_type=sa.String(),
                    nullable=True)
    
    # Reverse changes for expensefixed table
    op.alter_column('expensefixed', 'installment',
                    new_column_name='installments',
                    type_=sa.Integer(),
                    existing_type=sa.String(),
                    nullable=True)
    
    # Reverse changes for expense table
    op.alter_column('expense', 'installment',
                    new_column_name='installments',
                    type_=sa.Integer(),
                    existing_type=sa.String(),
                    nullable=True)
