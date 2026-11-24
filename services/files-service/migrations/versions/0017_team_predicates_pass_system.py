"""SQL Server: the files team predicate functions pass files' system user

The retention purge lists every tenant's released knowledge snapshots as ops_files_system (files_0014), which on
PostgreSQL bypasses row security. On SQL Server ops_files_system is a database user without a login
(deploy/database/mssql.py SYSTEM_USERS), and files_0011 and files_0013 made the team predicate functions admitting no
system user, so that listing read nothing and the migrated functions differed from the golden DDL. The functions are
schema-bound to every policy that uses them, so each files team table loses its policy, the two team functions are
made again passing the system user, and each policy comes back. Downgrade makes them again without it. Nothing changes
on PostgreSQL.

Revision ID: files_0017
Revises: files_0016
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TENANT_SCOPED, mssql_team_predicates_reissue_ddl, team_owned

revision = "files_0017"
down_revision = "files_0016"
branch_labels = None
depends_on = None

CHAIN = "files"
SYSTEM_ROLE = "ops_files_system"
# Every files table a team policy binds to the team functions at this revision (files_0011, files_0013).
TEAM_TABLES = ("files", "file_blobs", "file_versions", "file_references", "file_legal_holds", "file_read_requests")


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
