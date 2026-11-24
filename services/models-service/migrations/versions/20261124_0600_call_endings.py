"""each logged model call keeps how its reply ended, whether it was declined, and the image detail asked for

A reply cut off at its length limit or declined by the model was logged as a clean call, so the log could not show
why a document read had no answer, and nothing recorded the image detail a read sent. Three nullable columns on both
call tables; rows from before stay null. The downgrade drops them.

Revision ID: 20261124_0600_call_endings
Revises: 20261122_2017_list_sort_indexes
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "20261124_0600_call_endings"
down_revision = "20261122_2017_list_sort_indexes"
branch_labels = None
depends_on = None

TABLES = ("model_call_log", "model_calls_untenanted")


def _columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("ended", sa.String(32)),
        sa.Column("declined", sa.Boolean),
        sa.Column("image_detail", sa.String(8)),
    ]


def upgrade() -> None:
    for table in TABLES:
        for column in _columns():
            op.add_column(table, column)


def downgrade() -> None:
    for table in TABLES:
        for name in ("image_detail", "declined", "ended"):
            op.drop_column(table, name)
