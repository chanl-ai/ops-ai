"""files and file_versions: a file from a watched folder is one entry per source file, with a scan per version

Every completed write returned the team's existing file with the same digest, so one source file changed at the
source could never get a version 2, and the same bytes in two folders folded into one entry. A file now has a source
scope and key (upload: its own id; source: the hash of the connection and the source's id for it), unique per team,
with the source's id and path beside it, when the source stopped listing it, and its access list as last read
(null when the source never said, [] when it listed nobody). Each version keeps the source's tag and its own scan
status, so a new version can wait on its scan while older ones still download.

Backfill: every file is an upload keyed by its id; every version takes its file's scan status. Downgrade drops the
columns and the index.

Revision ID: 20261123_2345_source_files
Revises: files_0017
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261123_2345_source_files"
down_revision = "files_0017"
branch_labels = None
depends_on = None

FILE_COLUMNS = ("source_scope", "source_key_hash", "source_id", "source_path", "removed_at", "access_list",
                "access_read_at")  # fmt: skip
VERSION_COLUMNS = ("source_tag", "scan_status", "scan_at")


def upgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        # The migrating role may own the tables; with FORCE on, row-level security would hide rows from the backfill.
        op.execute("SET LOCAL row_security = off")
    with op.batch_alter_table("files") as b:
        b.add_column(sa.Column("source_scope", sa.String(16)))
        b.add_column(sa.Column("source_key_hash", sa.String(64)))
        b.add_column(sa.Column("source_id", sa.String(1024)))
        b.add_column(sa.Column("source_path", sa.String(1024)))
        b.add_column(sa.Column("removed_at", sa.DateTime(timezone=True)))
        b.add_column(sa.Column("access_list", sa.JSON))
        b.add_column(sa.Column("access_read_at", sa.DateTime(timezone=True)))
    f = sa.table("files", sa.column("id", sa.String), sa.column("scan_status", sa.String),
                 sa.column("source_scope", sa.String), sa.column("source_key_hash", sa.String))  # fmt: skip
    op.execute(sa.update(f).values(source_scope="upload", source_key_hash=f.c.id))
    with op.batch_alter_table("files") as b:
        b.alter_column("source_scope", existing_type=sa.String(16), nullable=False)
        b.alter_column("source_key_hash", existing_type=sa.String(64), nullable=False)
    op.create_index(
        "ux_files_source_key", "files", ["tenant_id", "team", "source_scope", "source_key_hash"], unique=True
    )
    with op.batch_alter_table("file_versions") as b:
        b.add_column(sa.Column("source_tag", sa.String(200)))
        b.add_column(sa.Column("scan_status", sa.String(16)))
        b.add_column(sa.Column("scan_at", sa.DateTime(timezone=True)))
    v = sa.table("file_versions", sa.column("file_id", sa.String), sa.column("scan_status", sa.String))
    of_file = sa.select(f.c.scan_status).where(f.c.id == v.c.file_id).scalar_subquery()
    op.execute(sa.update(v).values(scan_status=sa.func.coalesce(of_file, "pending")))
    with op.batch_alter_table("file_versions") as b:
        b.alter_column("scan_status", existing_type=sa.String(16), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("file_versions") as b:
        for name in VERSION_COLUMNS:
            b.drop_column(name)
    op.drop_index("ux_files_source_key", table_name="files")
    with op.batch_alter_table("files") as b:
        for name in FILE_COLUMNS:
            b.drop_column(name)
