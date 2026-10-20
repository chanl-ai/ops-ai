"""engine_definitions: archived_at and archived_by, set on every version of an archived workflow (c-274)

An archived workflow starts no run of any mode and leaves the workflow lists; its versions and runs are kept, and
restoring it clears both columns.

Revision ID: 0070_engine_definitions_archived
Revises: 0069_case_types
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0070_engine_definitions_archived"
down_revision = "0069_case_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("engine_definitions", sa.Column("archived_at", sa.String(32)))
    op.add_column("engine_definitions", sa.Column("archived_by", sa.String(200)))


def downgrade() -> None:
    op.drop_column("engine_definitions", "archived_by")
    op.drop_column("engine_definitions", "archived_at")
