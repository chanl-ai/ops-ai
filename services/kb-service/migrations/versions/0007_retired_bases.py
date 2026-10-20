"""a retired knowledge base leaves a tombstone (c-094 T007)

Revision ID: kb_0007
Revises: kb_0006

Agents name the bases they cite by id. A deleted base was an unknown id, so kb-service refused every search that
named it and an agent citing it lost all its knowledge, not just the retired base. The tombstone lets a search skip
the retired id while still refusing ids it never had, and stops the dev seed bringing a retired demo base back.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "kb_0007"
down_revision = "kb_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kb_retired_bases",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("retired_by", sa.String(200), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    )


def downgrade() -> None:
    op.drop_table("kb_retired_bases")
