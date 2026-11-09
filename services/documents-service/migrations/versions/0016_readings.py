"""Readings replace layouts

Revision ID: documents_0016
Revises: documents_0015

A file is read once per tenant, content digest, reader version and OCR settings into documents_readings, with its
pages one row each in documents_reading_pages, so a long read carries on from its next page after a restart. Which
files hold those bytes is kept in documents_reading_files, for the events a finished reading sends and for removing a
reading once no file holds its bytes. The layouts cache they replace is dropped: layouts are now drawn from readings.
Full-text reads stored as extractions are deleted, since a file's text is its reading. Runs on PostgreSQL and SQL
Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "documents_0016"
down_revision = "documents_0015"
branch_labels = None
depends_on = None

CHAIN = "documents"
ROLE = "ops_documents_tenant"
SYSTEM_ROLE = "ops_documents_system"
TABLES = ("documents_readings", "documents_reading_pages", "documents_reading_files")


def _key() -> list[sa.Column[Any]]:
    return [
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("file_digest", sa.String(64), primary_key=True),
        sa.Column("reader_version", sa.String(32), primary_key=True),
        sa.Column("settings_key", sa.String(64), primary_key=True),
    ]


def _marked(name: str) -> sa.Table:
    return sa.Table(name, sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        "documents_readings",
        *_key(),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("pages_total", sa.Integer),
        sa.Column("pages_done", sa.Integer, nullable=False),
        sa.Column("facts", sa.Text),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error", sa.Text),
        sa.Column("attempts", sa.Integer, nullable=False),
        sa.Column("file_id", sa.String(64), nullable=False),
        sa.Column("team", sa.String(64), nullable=False),
        sa.Column("actor", sa.String(320), nullable=False),
        sa.Column("duration_ms", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_documents_readings_status", "documents_readings", ["status"])
    op.create_table(
        "documents_reading_pages",
        *_key(),
        sa.Column("page", sa.Integer, primary_key=True),
        sa.Column("body", sa.LargeBinary, nullable=False),
    )
    op.create_table(
        "documents_reading_files",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("file_id", sa.String(64), primary_key=True),
        sa.Column("team", sa.String(64), primary_key=True),
        sa.Column("file_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_documents_reading_files_digest", "documents_reading_files", ["tenant_id", "file_digest"])
    extractions = sa.table("extractions", sa.column("request", sa.Text))
    # request is JSON text written by json.dumps, so a full-text read holds exactly this pair.
    op.execute(sa.delete(extractions).where(extractions.c.request.like('%"read": "text"%')))
    if dialect in ("postgresql", "mssql"):
        for statement in isolation_drop_ddl(_marked("documents_layouts"), dialect):
            op.execute(statement)
    op.drop_table("documents_layouts")
    tables = [_marked(n) for n in TABLES]
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=None):
            op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    if dialect == "postgresql":
        for name in TABLES:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO {ROLE}")
        # A restart reads every tenant's unfinished readings to pick them up again.
        op.execute(f"GRANT SELECT ON documents_readings TO {SYSTEM_ROLE}")
    for t in tables:
        for statement in isolation_ddl(t, dialect, chain=CHAIN):
            op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "mssql"):
        for name in TABLES:
            for statement in isolation_drop_ddl(_marked(name), dialect):
                op.execute(statement)
    op.drop_table("documents_reading_files")
    op.drop_table("documents_reading_pages")
    op.drop_index("ix_documents_readings_status", table_name="documents_readings")
    op.drop_table("documents_readings")
    op.create_table(
        "documents_layouts",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("file_digest", sa.String(64), primary_key=True),
        sa.Column("engine", sa.String(32), primary_key=True),
        sa.Column("ocr", sa.Boolean, primary_key=True),
        sa.Column("pages", sa.Integer, nullable=False),
        sa.Column("layout", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    if dialect == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON documents_layouts TO {ROLE}")
    if dialect in ("postgresql", "mssql"):
        for statement in isolation_ddl(_marked("documents_layouts"), dialect, chain=CHAIN):
            op.execute(statement)
