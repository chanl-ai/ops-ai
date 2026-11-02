"""team_defaults: which version of tools-service's declared team defaults each team has (c-616 provisioning)

A team's built-in apps are written by an idempotent reconciler; this row says which version it last applied, so a new
version reaches every team on the next start and a current team is not written again.

Revision ID: tools_0054_team_defaults
Revises: tools_0053_operation_example
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0054_team_defaults"
down_revision = "tools_0053_operation_example"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "team_defaults",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("team_id", sa.String(64), primary_key=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("team_defaults")
