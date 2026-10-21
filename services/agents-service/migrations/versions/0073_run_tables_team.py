"""The run tables are held to the caller's team by the database (c-429)

Revision ID: 0073_run_tables_team
Revises: 0072_memories_system_tenants

graph_threads, graph_runs, thread_events, review_decisions and review_approvals were isolated by tenant only, so a
store query that forgot its team clause read another team's conversations and decisions. Each now carries the
generated `{t}_isolation` policy (ops_store.schema.isolation_ddl), which replaces `{t}_tenant`: a team transaction
reads its team's rows (and none with no team, as every row has one after this) and writes only its own; a tenant-wide
transaction, opened only through a named reason, reads every team of its tenant.

graph_runs, review_decisions and review_approvals had a nullable team; each row takes its thread's team (a review row
written for a workflow run takes the run's), the migration stops naming any row it cannot place, and the column becomes
NOT NULL. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any, Literal

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, mssql_predicates_ddl

revision = "0073_run_tables_team"
down_revision = "0072_memories_system_tenants"
branch_labels = None
depends_on = None

CHAIN = "agents"
SYSTEM_USER = "ops_runtime_system"
TABLES = ("graph_threads", "graph_runs", "thread_events", "review_decisions", "review_approvals")
# The tables whose team was nullable, each filled from its thread.
FILLED = ("graph_runs", "review_decisions", "review_approvals")


def _marked(name: str) -> sa.Table:
    """The table as far as its isolation needs: its tenant and team columns and markings, as of this revision."""
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
    if dialect == "mssql" and kind == "team":
        for statement in mssql_predicates_ddl(CHAIN, tables, column_type=_column_type, system_user=SYSTEM_USER):
            op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    for t in tables:
        for statement in isolation_ddl(t, dialect, kind=kind, chain=CHAIN):
            op.execute(statement)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # The migrating role may own the tables; FORCE row-level security would otherwise hide every row from it.
        op.execute("SET LOCAL row_security = off")
    # A review row names a graph thread, or a workflow run when an engine review approved a call under the run's id.
    owners = [sa.table(o, sa.column("id"), sa.column("team_id")) for o in ("graph_threads", "engine_runs")]
    for name in FILLED:
        t = sa.table(name, sa.column("thread_id"), sa.column("team_id"))
        team = sa.func.coalesce(
            *(sa.select(o.c.team_id).where(o.c.id == t.c.thread_id).scalar_subquery() for o in owners)
        )
        op.execute(sa.update(t).where(t.c.team_id.is_(None)).values(team_id=team))
        # Offline SQL (a DBA's upgrade script) cannot count; NOT NULL then refuses a row left behind on its own.
        left = (
            0
            if context.is_offline_mode()
            else bind.execute(sa.select(sa.func.count()).select_from(t).where(t.c.team_id.is_(None))).scalar_one()
        )
        if left:
            raise RuntimeError(f"{name}: {left} rows have no thread or run to take a team from; place them first")
        with op.batch_alter_table(name) as b:
            b.alter_column("team_id", existing_type=sa.String(64), nullable=False)
    _isolate("team")


def downgrade() -> None:
    _isolate("tenant")
    for name in reversed(FILLED):
        with op.batch_alter_table(name) as b:
            b.alter_column("team_id", existing_type=sa.String(64), nullable=True)
