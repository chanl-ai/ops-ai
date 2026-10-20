"""kb_bases name their documents source by id (c-159)

Revision ID: kb_0009
Revises: kb_0008

Add documents found a base's documents source by its display name, so renaming the base made a second source. The
base now records the source's id; a base that already has one, attached under the name it was made with, keeps it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "kb_0009"
down_revision = "kb_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_bases", sa.Column("documents_source_id", sa.String(64), nullable=True))
    op.execute(
        """
        UPDATE kb_bases b SET documents_source_id = s.id
        FROM kb_base_sources l JOIN kb_sources s ON s.tenant_id = l.tenant_id AND s.id = l.source_id
        WHERE l.tenant_id = b.tenant_id AND l.kb_id = b.id AND s.name = b.name || ' documents'
        """
    )


def downgrade() -> None:
    pass
