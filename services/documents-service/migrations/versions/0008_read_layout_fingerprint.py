"""a read keeps its layout fingerprint, and a type's recent reads are found by index (c-254)

Template offers grouped a type's last 200 reads by layout by reading every one of those files' layouts again on each
request. A model read now stores its fingerprint when it finishes, and the offers group the stored values; reads
saved before get theirs on the first offers request that sees them. The index serves the recent-reads query.

Revision ID: documents_0008
Revises: documents_0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "documents_0008"
down_revision = "documents_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("extractions", sa.Column("layout_fingerprint", sa.String(32), nullable=True))
    op.create_index(
        "ix_extractions_type_reads", "extractions", ["tenant_id", "team", "type_id", "status", "finished_at"]
    )
