"""per-tenant budgets on a shared key (c-251)

Revision ID: models_0003
Revises: models_0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "models_0003"
down_revision = "models_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_keys", sa.Column("tenant_budget", sa.Numeric(18, 6), nullable=True))
    op.add_column("model_call_log", sa.Column("tenant_id", sa.String(length=64), nullable=True))
    op.create_table(
        "model_key_tenants",
        sa.Column("key_id", sa.String(length=200), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("budget", sa.Numeric(18, 6), nullable=False),
        sa.Column("spent", sa.Numeric(18, 6), nullable=False),
        sa.PrimaryKeyConstraint("key_id", "tenant_id"),
    )


def downgrade() -> None:
    pass
