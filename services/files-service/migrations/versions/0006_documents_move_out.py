"""extractions and document types leave files-service for documents-service (c-256)

Files keeps the bytes; what is read from them moved to documents-service, under its own chain (documents_0001). The
earlier revisions that created those tables here now create nothing, so this one drops nothing. A sample's
`test_set` reference would keep its file from ever being deleted once no sample row remained here, so those
references go.

Revision ID: files_0006
Revises: files_0005
"""

from __future__ import annotations

from alembic import op

revision = "files_0006"
down_revision = "files_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drops nothing: the tables are documents_0001's now, and a database that ran documents' chain first holds them.
    op.execute("DELETE FROM file_references WHERE ref_type = 'test_set'")


def downgrade() -> None:
    pass
