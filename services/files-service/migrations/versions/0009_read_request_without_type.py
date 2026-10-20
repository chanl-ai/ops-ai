"""a read request may name no document type, so the file is read with Detect (c-335)

Revision ID: files_0009
Revises: files_0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "files_0009"
down_revision = "files_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("file_read_requests", "document_type_id", existing_type=sa.String(length=64), nullable=True)
