"""a document type's examples, from the corrections people make on its reads (c-297)

Each correction of a read of a type keeps the field, the line its value was printed on and the corrected value, for the
tenant, team and type; later model reads of the type are given the most recent few. One per read and field: a later
correction of the same field on the same read replaces it. `record` is the record's position, -1 for a read of one.

Revision ID: documents_0010
Revises: documents_0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "documents_0010"
down_revision = "documents_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_type_examples",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("team", sa.String(length=64), nullable=False),
        sa.Column("type_id", sa.String(length=64), nullable=False),
        sa.Column("field", sa.String(length=128), nullable=False),
        sa.Column("line", sa.Text(), nullable=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("extraction_id", sa.String(length=64), nullable=False),
        sa.Column("record", sa.Integer(), nullable=False),
        sa.Column("corrected_by", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "extraction_id", "field", "record", name="uq_document_type_examples_read"),
    )
    op.create_index(
        "ix_document_type_examples_type", "document_type_examples", ["tenant_id", "team", "type_id", "created_at"]
    )
