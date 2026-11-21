"""A workflow may store one definition at more than one version

Revision ID: 0122_definition_digest_index
Revises: 0121_engine_working_copies

Restoring an older version and publishing it makes a new draft version with the older one's definition, so the
version that goes live is the next number and the history keeps the rollback. `uq_engine_definitions_digest` refused
that insert. It becomes a plain index on the same columns: publishing a definition already stored still finds its
version through it, and the primary key (tenant, workflow, version) keeps two saves from taking one number.

The down path puts the unique constraint back, which fails while a workflow holds one definition at two versions.
"""

from __future__ import annotations

from alembic import op

revision = "0122_definition_digest_index"
down_revision = "0121_engine_working_copies"
branch_labels = None
depends_on = None

TABLE = "engine_definitions"
COLUMNS = ["tenant_id", "workflow_id", "digest"]


def upgrade() -> None:
    op.drop_constraint("uq_engine_definitions_digest", TABLE, type_="unique")
    op.create_index("ix_engine_definitions_digest", TABLE, COLUMNS)


def downgrade() -> None:
    op.drop_index("ix_engine_definitions_digest", table_name=TABLE)
    op.create_unique_constraint("uq_engine_definitions_digest", TABLE, COLUMNS)
