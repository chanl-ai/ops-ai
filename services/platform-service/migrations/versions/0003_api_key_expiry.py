"""an optional expiry on API keys, set from the lifetime chosen at creation

Revision ID: 0003_key_expiry
Revises: 0002_tenant_fks
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_key_expiry"
down_revision = "0002_tenant_fks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("api_keys", sa.Column("expires_at", sa.String(40)))


def downgrade() -> None:
    op.drop_column("api_keys", "expires_at")
