"""user language

Revision ID: 9a1c2e7f5b30
Revises: 4c87cf8c3997
Create Date: 2026-11-20 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a1c2e7f5b30'
down_revision: Union[str, None] = '4c87cf8c3997'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('language', sa.String(length=2), server_default='en', nullable=False))
    op.create_check_constraint(op.f('ck_users_language'), 'users', "language IN ('en', 'pt')")


def downgrade() -> None:
    op.drop_constraint(op.f('ck_users_language'), 'users', type_='check')
    op.drop_column('users', 'language')
