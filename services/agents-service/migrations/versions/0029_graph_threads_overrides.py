"""graph_threads.overrides: a chat thread's overrides within its agent's limits

Revision ID: 0029_graph_threads_overrides
Revises: 0028_engine_definitions_row_lock

Applied to every turn in the thread through the resolver (activities/overrides.py, c-071); a turn may narrow them.
The tenant role already updates graph_threads, so no grant changes.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_graph_threads_overrides"
down_revision = "0028_engine_definitions_row_lock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("graph_threads") as b:
        b.add_column(sa.Column("overrides", sa.JSON))


def downgrade() -> None:
    with op.batch_alter_table("graph_threads") as b:
        b.drop_column("overrides")
