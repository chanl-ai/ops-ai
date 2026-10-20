"""a document type version's date order (levy demo, c-270)

How a version reads a numeric date: MDY (03/04/2026 is March 4, as US levies write it) or DMY. Versions saved before it
was a setting read null, which means MDY.

Revision ID: documents_0003
Revises: documents_0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "documents_0003"
down_revision = "documents_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_type_versions", sa.Column("date_order", sa.String(length=3), nullable=True))


def downgrade() -> None:
    pass
