"""kb_bases carry a template id and a protection level (c-180)

Revision ID: kb_0008
Revises: kb_0007

The provisioning service (c-175) finds a knowledge base again by the template it was made from, and marks it `system`
(no person may change it) or `managed` (people may; the template's fields come back on the next run). Both are null on
every knowledge base made before.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "kb_0008"
down_revision = "kb_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("kb_bases", sa.Column("template_id", sa.String(120), nullable=True))
    op.add_column("kb_bases", sa.Column("protection", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("kb_bases", "protection")
    op.drop_column("kb_bases", "template_id")
