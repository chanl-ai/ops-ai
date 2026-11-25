"""SQL Server: the documents team predicate functions pass documents' system user

The documents outbox relay and the readings restart read every tenant's rows as ops_documents_system, which on
PostgreSQL bypasses row security. On SQL Server it is a database user without a login (deploy/database/mssql.py
SYSTEM_USERS), and documents_0011, documents_0013 and documents_0017 made the team predicate functions admitting no
system user, so the migrated functions differed from the golden DDL and those reads saw no team rows. The functions are
schema-bound to every policy that uses them, so each documents team table loses its policy, the two team functions are
made again passing the system user, and each policy comes back. Downgrade makes them again without it. Nothing changes
on PostgreSQL.

Revision ID: documents_0020
Revises: documents_0019
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TENANT_SCOPED, mssql_team_predicates_reissue_ddl, team_owned

revision = "documents_0020"
down_revision = "documents_0019"
branch_labels = None
depends_on = None

CHAIN = "documents"
SYSTEM_ROLE = "ops_documents_system"
# Every documents table a team policy binds to the team functions at this revision (documents_0011, _0013, _0014, _0016,
# _0017).
TEAM_TABLES = (
    "document_types",
    "document_type_versions",
    "document_type_examples",
    "document_type_samples",
    "document_type_tests",
    "extractions",
    "extraction_corrections",
    "documents_template_copies",
    "documents_readings",
    "documents_reading_files",
    "documents_reading_pages",
)


def _marked(name: str) -> sa.Table:
    return sa.Table(
        name,
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team", sa.String(64)),
        info={**TENANT_SCOPED, **team_owned("team")},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _reissue(system_user: str | None) -> None:
    tables = [_marked(t) for t in TEAM_TABLES]
    for statement in mssql_team_predicates_reissue_ddl(
        CHAIN, tables, column_type=_column_type, system_user=system_user
    ):
        op.execute(statement)


def upgrade() -> None:
    if op.get_context().dialect.name == "mssql":
        _reissue(SYSTEM_ROLE)


def downgrade() -> None:
    if op.get_context().dialect.name == "mssql":
        _reissue(None)
