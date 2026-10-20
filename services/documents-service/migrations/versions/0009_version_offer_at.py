"""a document type version sets how many reads of one layout offer a template (c-254)

The owner's rule (2026-10-18) is 5, changeable per type; the number was fixed in code. Versions saved before hold
null, read as 5.

Revision ID: documents_0009
Revises: documents_0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "documents_0009"
down_revision = "documents_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_type_versions", sa.Column("offer_at", sa.Integer(), nullable=True))
