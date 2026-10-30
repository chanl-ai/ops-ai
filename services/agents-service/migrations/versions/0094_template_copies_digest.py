"""Template copies keep the digest of the body they were made from (c-590)

Revision ID: 0094_template_copies_digest
Revises: 0093_template_copies

A copy records the sha256 of the template body it was made from, the baseline that shows a template changed since a
copy was installed even at the same version. Nullable: copies made before carry none. Runs on PostgreSQL and SQL
Server.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0094_template_copies_digest"
down_revision = "0093_template_copies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("template_copies") as b:
        b.add_column(sa.Column("digest", sa.String(64)))


def downgrade() -> None:
    with op.batch_alter_table("template_copies") as b:
        b.drop_column("digest")
