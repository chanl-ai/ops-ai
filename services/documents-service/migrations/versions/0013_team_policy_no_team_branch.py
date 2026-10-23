"""No team policy reads a row with no team (c-507)

Revision ID: documents_0013
Revises: documents_0012

The generated team policy (ops_store.schema) no longer has its no-team branch. Every row of these tables has a
team since documents_0011, so each policy is reissued with the text the schema now generates and reads the same rows. On
SQL Server the chain's team predicate functions are bound to every team policy, so all of them are dropped and
created again. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TENANT_SCOPED, isolation_ddl, mssql_team_predicates_reissue_ddl, team_owned

revision = "documents_0013"
down_revision = "documents_0012"
branch_labels = None
depends_on = None

CHAIN = "documents"
TEAM_TABLES = (
    "document_types",
    "document_type_versions",
    "document_type_samples",
    "document_type_tests",
    "document_type_examples",
    "extractions",
    "extraction_corrections",
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


def _reissue(*, reads_no_team: bool) -> None:
    dialect = op.get_bind().dialect.name
    tables = [_marked(t) for t in TEAM_TABLES]
    if dialect == "mssql":
        for statement in mssql_team_predicates_reissue_ddl(
            CHAIN, tables, column_type=_column_type, system_user=None, reads_no_team=reads_no_team
        ):
            op.execute(statement)
    elif dialect == "postgresql":
        for t in tables:
            for statement in isolation_ddl(t, dialect, kind="team", reads_no_team=reads_no_team):
                op.execute(statement)


def upgrade() -> None:
    _reissue(reads_no_team=False)


def downgrade() -> None:
    _reissue(reads_no_team=True)
