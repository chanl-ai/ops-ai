"""documents-service's tables: extractions and corrections, document types, versions, samples and test runs (c-256)

They moved here from files-service (files_0004, files_0005); pre-launch, nothing is copied.

Revision ID: documents_0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "documents_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "extractions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("team", sa.String(length=64), nullable=False),
        sa.Column("file_id", sa.String(length=64), nullable=False),
        sa.Column("file_digest", sa.String(length=64), nullable=False),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("schema_digest", sa.String(length=64), nullable=False),
        sa.Column("alias", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("asked_by", sa.String(length=320), nullable=False),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "key_hash", name="uq_extractions_key"),
    )
    op.create_index("ix_extractions_status", "extractions", ["status"], unique=False)
    op.create_index("ix_extractions_file", "extractions", ["tenant_id", "file_id"], unique=False)
    op.create_table(
        "extraction_corrections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("extraction_id", sa.String(length=64), nullable=False),
        sa.Column("field", sa.String(length=128), nullable=False),
        sa.Column("record", sa.Integer(), nullable=True),
        sa.Column("original", sa.Text(), nullable=False),
        sa.Column("original_confidence", sa.Float(), nullable=False),
        sa.Column("corrected", sa.Text(), nullable=False),
        sa.Column("corrected_by", sa.String(length=320), nullable=False),
        sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_extraction_corrections_extraction", "extraction_corrections", ["tenant_id", "extraction_id"], unique=False
    )

    op.create_table(
        "document_types",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("team", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("latest_version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
        sa.UniqueConstraint("tenant_id", "team", "name", name="uq_document_types_name"),
    )
    op.create_table(
        "document_type_versions",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("type_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("fields", sa.Text(), nullable=False),
        sa.Column("many", sa.Boolean(), nullable=False),
        sa.Column("review_below", sa.Float(), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_by", sa.String(length=320), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "type_id", "version"),
    )
    op.create_table(
        "document_type_samples",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("type_id", sa.String(length=64), nullable=False),
        sa.Column("file_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("expected", sa.Text(), nullable=False),
        sa.Column("added_by", sa.String(length=320), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    )
    op.create_index("ix_document_type_samples_type", "document_type_samples", ["tenant_id", "type_id"], unique=False)
    op.create_table(
        "document_type_tests",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("type_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("team", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("samples", sa.Integer(), nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("asked_by", sa.String(length=320), nullable=False),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("tenant_id", "id"),
    )
    op.create_index(
        "ix_document_type_tests_type", "document_type_tests", ["tenant_id", "type_id", "version"], unique=False
    )
    op.create_index("ix_document_type_tests_status", "document_type_tests", ["status"], unique=False)


def downgrade() -> None:
    pass
