"""files a document type is tested against carry their own purpose, document_type_sample (c-379)

The document types' seed uploaded its sample PDFs as case attachments, so Files labelled them "Email attachment". A file
kept only by `test_set` references, which documents-service adds for a type's samples and nothing else does, takes the
sample purpose. One also kept by a case, chat or any other reference keeps the purpose it was uploaded with.

Revision ID: files_0010
Revises: files_0009
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "files_0010"
down_revision = "files_0009"
branch_labels = None
depends_on = None

# Typed, so offline SQL (make db-upgrade-sql) can render the literals; an untyped column has no literal renderer.
files = sa.table(
    "files", sa.column("tenant_id", sa.String), sa.column("id", sa.String), sa.column("purpose", sa.String)
)
refs = sa.table(
    "file_references",
    sa.column("tenant_id", sa.String),
    sa.column("file_id", sa.String),
    sa.column("ref_type", sa.String),
)


def _refs(*where: sa.ColumnElement[bool]) -> sa.Exists:
    return sa.exists().where(refs.c.tenant_id == files.c.tenant_id, refs.c.file_id == files.c.id, *where)


RELABEL = (
    sa.update(files)
    .where(
        files.c.purpose.in_(("case_attachment", "chat_attachment")),
        _refs(refs.c.ref_type == "test_set"),
        ~_refs(refs.c.ref_type != "test_set"),
    )
    .values(purpose="document_type_sample")
)


def upgrade() -> None:
    op.execute(RELABEL)
