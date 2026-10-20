"""a document type version may show the model the page image (c-295)

Off on every version saved before: a page image carries everything printed on the page to the model provider, so a
version sends one only when someone who may manage the team's documents turned it on.

Revision ID: documents_0007
Revises: documents_0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "documents_0007"
down_revision = "documents_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_type_versions", sa.Column("page_images", sa.Boolean(), nullable=True))
