"""a document type version's checks across fields (c-296)

Checks are part of the version, like its fields and templates: a total that must equal the sum of its parts, a date
that must come before another. Versions saved before hold none.

Revision ID: documents_0006
Revises: documents_0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "documents_0006"
down_revision = "documents_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_type_versions", sa.Column("checks", sa.Text(), nullable=True))


def downgrade() -> None:
    pass
