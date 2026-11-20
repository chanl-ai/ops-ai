"""A model call is reserved against its budget before it runs

Revision ID: 0120_model_call_reservations
Revises: 0119_unattributed_side_tables

A budget check summed the recorded rows of model_call_records, and a call's row was written only after its provider
answered, so calls made at once each read the same total and passed together. `reserved_until` lets a call be in the
table before it runs: the row is written with the column set, in the transaction that checks the budget, and the
call's record replaces it when the call returns (store/usage.py `UsageLedger.reserve`). NULL on every recorded call,
so rows written before this step need no fill.

The down path drops the column and, first, any reservation still held, which would otherwise read as a recorded
call. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0120_model_call_reservations"
down_revision = "0119_unattributed_side_tables"
branch_labels = None
depends_on = None

TABLE = "model_call_records"
COLUMN = "reserved_until"


def upgrade() -> None:
    with op.batch_alter_table(TABLE) as b:
        b.add_column(sa.Column(COLUMN, sa.String(40)))


def downgrade() -> None:
    held = sa.table(TABLE, sa.column(COLUMN))
    op.execute(sa.delete(held).where(held.c[COLUMN].is_not(None)))
    with op.batch_alter_table(TABLE) as b:
        b.drop_column(COLUMN)
