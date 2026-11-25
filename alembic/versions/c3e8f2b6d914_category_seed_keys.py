"""category seed keys and default income categories

Built-in categories get a `seed_key` so the UI can show them in the user's language until they
are renamed. Existing built-in categories are recognised by their English or Portuguese name.
Households also get the default income categories they don't have yet.

Revision ID: c3e8f2b6d914
Revises: b7d4e1a9c260
Create Date: 2026-11-25 10:00:00.000000

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3e8f2b6d914'
down_revision: Union[str, None] = 'b7d4e1a9c260'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# A snapshot of app.services.households.SEED_CATEGORIES, so this migration doesn't change with it.
SEEDS = {
    'EXPENSE': [
        ('food', 'Food', 'Alimentação'), ('gasoline', 'Gasoline', 'Combustível'), ('car', 'Car', 'Carro'),
        ('house', 'House', 'Casa'), ('rent', 'Rent', 'Aluguel'), ('courses', 'Courses', 'Cursos'),
        ('music', 'Music', 'Música'), ('clothes', 'Clothes', 'Roupas'), ('health', 'Health', 'Saúde'),
        ('pharmacy', 'Pharmacy', 'Farmácia'), ('gym', 'Gym', 'Academia'), ('kids', 'Kids', 'Filhos'),
        ('trips', 'Trips', 'Viagens'), ('transport', 'Transport', 'Transporte'),
        ('entertainment', 'Entertainment', 'Lazer'), ('birthdays', 'Birthdays', 'Aniversários'),
        ('gas', 'Gas', 'Gás'), ('electricity', 'Electricity', 'Energia'), ('internet', 'Internet', 'Internet'),
        ('ai', 'AI', 'IA'), ('storage', 'Storage', 'Armazenamento'), ('phone', 'Phone', 'Telefone'),
        ('business', 'Business', 'Negócios'), ('tax', 'Tax', 'Impostos'), ('other', 'Other', 'Outros'),
    ],
    'INCOME': [
        ('salary', 'Salary', 'Salário'), ('investments', 'Investments', 'Investimentos'),
        ('other', 'Other', 'Outros'),
    ],
}


def upgrade() -> None:
    op.add_column('categories', sa.Column('seed_key', sa.String(length=30), nullable=True))
    conn = op.get_bind()
    for entry_type, seeds in SEEDS.items():
        for key, en, pt in seeds:
            conn.execute(sa.text(
                "UPDATE categories SET seed_key = :key WHERE type = :type AND lower(name) IN (lower(:en), lower(:pt))"
            ), {"key": key, "type": entry_type, "en": en, "pt": pt})

    households = conn.execute(sa.text(
        "SELECT h.id, coalesce((SELECT u.language FROM users u WHERE u.household_id = h.id "
        "ORDER BY u.created_at LIMIT 1), 'en') FROM households h"
    )).all()
    for household_id, language in households:
        for key, en, pt in SEEDS['INCOME']:
            conn.execute(sa.text(
                "INSERT INTO categories (id, household_id, type, name, seed_key, is_active, created_at, updated_at) "
                "SELECT CAST(:id AS uuid), CAST(:household AS uuid), 'INCOME', CAST(:name AS varchar), "
                "CAST(:key AS varchar), true, now(), now() "
                "WHERE NOT EXISTS (SELECT 1 FROM categories WHERE household_id = CAST(:household AS uuid) "
                "AND type = 'INCOME' AND (seed_key = CAST(:key AS varchar) "
                "OR lower(name) IN (lower(CAST(:en AS varchar)), lower(CAST(:pt AS varchar)))))"
            ), {"id": uuid.uuid4(), "household": household_id, "name": pt if language == 'pt' else en,
                "key": key, "en": en, "pt": pt})


def downgrade() -> None:
    op.drop_column('categories', 'seed_key')
