"""files, blobs, versions, references and legal holds

Revision ID: files_0001
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "files_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_blobs",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("team", sa.String(length=64), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("file_id", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "team", "digest"),
    )
    op.create_table(
        "file_legal_holds",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("file_id", sa.String(length=64), nullable=False),
        sa.Column("placed_by", sa.String(length=320), nullable=False),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("released_by", sa.String(length=320), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_file_legal_holds_file", "file_legal_holds", ["file_id", "released_at"], unique=False)
    op.create_table(
        "file_references",
        sa.Column("file_id", sa.String(length=64), nullable=False),
        sa.Column("ref_type", sa.String(length=32), nullable=False),
        sa.Column("ref_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("owner_service", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("href", sa.String(length=512), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocked", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("file_id", "ref_type", "ref_id"),
    )
    op.create_index("ix_file_references_owner", "file_references", ["tenant_id", "ref_type", "ref_id"], unique=False)
    op.create_table(
        "file_versions",
        sa.Column("file_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("uploaded_by", sa.String(length=320), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("current", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("file_id", "version"),
    )
    op.create_table(
        "files",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("team", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("mime", sa.String(length=127), nullable=False),
        sa.Column("sniffed_mime", sa.String(length=127), nullable=True),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("digest", sa.String(length=64), nullable=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("scan_status", sa.String(length=16), nullable=False),
        sa.Column("scan_engine", sa.String(length=64), nullable=True),
        sa.Column("scan_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scan_detail", sa.String(length=500), nullable=True),
        sa.Column("sensitivity", sa.String(length=16), nullable=False),
        sa.Column("sensitivity_suggested", sa.Boolean(), nullable=False),
        sa.Column("retention_class_id", sa.String(length=64), nullable=False),
        sa.Column("delete_after", sa.Date(), nullable=True),
        sa.Column("immutable", sa.Boolean(), nullable=False),
        sa.Column("storage_backend", sa.String(length=16), nullable=False),
        sa.Column("storage_container", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("multipart_upload_id", sa.String(length=255), nullable=True),
        sa.Column("declared_size", sa.BigInteger(), nullable=False),
        sa.Column("declared_digest", sa.String(length=64), nullable=True),
        sa.Column("upload_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_by", sa.String(length=320), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_files_delete_after", "files", ["tenant_id", "delete_after"], unique=False)
    op.create_index("ix_files_team_status", "files", ["tenant_id", "team", "status", "uploaded_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_files_team_status", table_name="files")
    op.drop_index("ix_files_delete_after", table_name="files")
    op.drop_table("files")
    op.drop_table("file_versions")
    op.drop_index("ix_file_references_owner", table_name="file_references")
    op.drop_table("file_references")
    op.drop_index("ix_file_legal_holds_file", table_name="file_legal_holds")
    op.drop_table("file_legal_holds")
    op.drop_table("file_blobs")
