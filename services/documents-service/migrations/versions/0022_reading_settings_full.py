"""A reading keeps its whole settings key when the key column cannot hold it

A long OCR language list with the picture suffix is longer than the 64-character key column; the key columns then hold
its hash and this column the whole key, so the reading still names its settings. Null for every key that fits. Runs on
PostgreSQL and SQL Server.

Revision ID: documents_0022
Revises: documents_0021
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "documents_0022"
down_revision = "documents_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents_readings", sa.Column("settings_full", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("documents_readings", "settings_full")
