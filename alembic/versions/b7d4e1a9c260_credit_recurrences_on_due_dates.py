"""credit card fixed expenses occur on the card's due dates

Before, an occurrence of a CREDIT fixed expense was a purchase date and was paid with the
statement that purchase fell into. Now the occurrence is the statement's due date itself
(schemas §12.1). Existing rows move to the due date of the bill they were paid with.

Revision ID: b7d4e1a9c260
Revises: 9a1c2e7f5b30
Create Date: 2026-11-24 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.domain.credit import CardCycle, statement_for_purchase
from app.domain.dates import clamp_date


revision: str = 'b7d4e1a9c260'
down_revision: Union[str, None] = '9a1c2e7f5b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    recs = conn.execute(sa.text(
        "SELECT r.id, r.start_date, r.skipped_dates, c.best_buy_day, c.due_day FROM recurrences r "
        "JOIN cards c ON c.id = r.card_id WHERE r.type = 'EXPENSE' AND r.payment_method = 'CREDIT'"
    )).all()
    for rec_id, start, skipped, best_buy_day, due_day in recs:
        cycle = CardCycle(best_buy_day, due_day)

        def bill(purchase):
            return statement_for_purchase(purchase, cycle).nominal_due_date

        rows = conn.execute(sa.text(
            "SELECT id, transaction_date, occurrence_date, payment_method FROM expenses "
            "WHERE recurrence_id = :id ORDER BY occurrence_date"
        ), {"id": rec_id}).all()
        taken: set = set()
        for row_id, transaction_date, occurrence, method in rows:
            # A credit payment belongs to its bill; one edited to another method keeps its month.
            new = bill(transaction_date) if method == 'CREDIT' else clamp_date(occurrence.year, occurrence.month, due_day)
            if new in taken:
                new = occurrence  # two payments for the same bill: leave the second one alone
            taken.add(new)
            conn.execute(sa.text("UPDATE expenses SET occurrence_date = :occ WHERE id = :id"), {"id": row_id, "occ": new})
        conn.execute(
            sa.text("UPDATE recurrences SET day_of_month = :day, start_date = :start, skipped_dates = :skipped WHERE id = :id"),
            {"id": rec_id, "day": due_day, "start": min([bill(start), *taken]),
             "skipped": sorted({bill(d) for d in skipped or []})},
        )


def downgrade() -> None:
    pass  # the old occurrence dates can't be recovered; the new ones remain valid rows
