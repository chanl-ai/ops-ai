"""an API key may be scoped to one agent or workflow

A key names what it may start (c-246): `target_kind` agent or workflow, `target_id`, and `target_version`, a pinned
workflow version or null for the live one. A key with no target starts any live workflow of its team, as before. The
columns sit on api_keys under its existing grants and row-level security.

Revision ID: 0022_api_key_target
Revises: 0021_cases_cells
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_api_key_target"
down_revision = "0021_cases_cells"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("api_keys") as t:
        t.add_column(sa.Column("target_kind", sa.String(16)))
        t.add_column(sa.Column("target_id", sa.String(64)))
        t.add_column(sa.Column("target_version", sa.Integer))


def downgrade() -> None:
    with op.batch_alter_table("api_keys") as t:
        t.drop_column("target_version")
        t.drop_column("target_id")
        t.drop_column("target_kind")
