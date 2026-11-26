"""user avatar

Revision ID: d5f1a7c3e208
Revises: c3e8f2b6d914
Create Date: 2026-11-26 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5f1a7c3e208'
down_revision: Union[str, None] = 'c3e8f2b6d914'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('avatar', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'avatar')
