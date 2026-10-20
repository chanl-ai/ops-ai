"""a document type version's layout templates (c-253)

Templates are part of the version, like its fields: a version is immutable, so a template change is a new version, and
every extraction names the version that read it. Versions saved before hold none.

Revision ID: documents_0005
Revises: documents_0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "documents_0005"
down_revision = "documents_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_type_versions", sa.Column("templates", sa.Text(), nullable=True))


def downgrade() -> None:
    pass
