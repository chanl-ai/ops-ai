"""Workflow runs and cases are held to the caller's team by the database (c-507)

Revision ID: 0076_runs_and_cases_team
Revises: 0075_definitions_have_a_team

engine_runs and cases had a team on every row but only the tenant policy, so a store query that forgot its team
clause read another team's runs and cases. Each now carries the generated `{t}_isolation` policy
(ops_store.schema.isolation_ddl), which replaces `{t}_tenant`: a team transaction reads and writes its own team's
rows; a tenant-wide transaction (a loop or a background process, opened through a named reason) reads every team of
its tenant. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any, Literal

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, mssql_predicates_ddl

revision = "0076_runs_and_cases_team"
down_revision = "0075_definitions_have_a_team"
branch_labels = None
depends_on = None

CHAIN = "agents"
SYSTEM_USER = "ops_runtime_system"
TABLES = ("engine_runs", "cases")


def _marked(name: str) -> sa.Table:
    """The table as far as its isolation needs, as of this revision."""
    return sa.Table(
        name,
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _isolate(kind: Literal["team", "tenant"]) -> None:
    dialect = op.get_bind().dialect.name
    tables = [_marked(t) for t in TABLES]
    if dialect == "mssql":
        # The chain's team functions exist since 0073 (reissued by 0074); this creates any that are missing.
        for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=SYSTEM_USER):
            op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    for t in tables:
        for statement in isolation_ddl(t, dialect, kind=kind, chain=CHAIN):
            op.execute(statement)


def upgrade() -> None:
    _isolate("team")


def downgrade() -> None:
    _isolate("tenant")
