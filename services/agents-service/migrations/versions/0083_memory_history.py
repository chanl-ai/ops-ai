"""Memories keep their history and say what each answer used (c-557)

Revision ID: 0083_memory_history
Revises: 0082_engine_waits

A memory had only superseded_at, so an undone save, a forgotten memory and a replaced one could not be told apart, and
nothing recorded which memories an answer used. agent_memories gains a status and the fields learning and recall read;
an empty agent_id now means every agent in the team. A unique index holds one memory in use per key for a person, so
two chats saving at once cannot both keep theirs. memory_audit gains the team and the team policy in place of the
tenant one. message_memory_use records the memory ids an answer used, never their text, with team isolation like
engine_waits. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, mssql_predicates_ddl

revision = "0083_memory_history"
down_revision = "0082_engine_waits"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
IN_USE = "status = 'active' AND \"key\" IS NOT NULL"


def _marked(name: str = "message_memory_use") -> sa.Table:
    return sa.Table(
        name,
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("quote", sa.String(500)),
        sa.Column("source_message_id", sa.String(64)),
        sa.Column("sensitivity", sa.String(16), nullable=False, server_default="none"),
        sa.Column("supersedes_id", sa.String(64)),
        sa.Column("confirmed_at", sa.String(32)),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.String(32)),
        sa.Column("erase_after", sa.String(32)),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        # The migrating role may own the table; FORCE row-level security would otherwise hide every row from it.
        op.execute("SET LOCAL row_security = off")
    for column in _columns():
        op.add_column("agent_memories", column)
    op.execute("UPDATE agent_memories SET status = 'superseded' WHERE superseded_at IS NOT NULL")
    # Saves that raced before this revision may have left two rows in use for one key: the newest stays.
    op.execute(
        "UPDATE agent_memories SET status = 'superseded', superseded_at = created_at "
        "WHERE status = 'active' AND \"key\" IS NOT NULL AND EXISTS ("
        "SELECT 1 FROM agent_memories n WHERE n.tenant_id = agent_memories.tenant_id "
        "AND n.team_id = agent_memories.team_id AND n.person = agent_memories.person "
        'AND n.agent_id = agent_memories.agent_id AND n."key" = agent_memories."key" AND n.status = \'active\' '
        "AND (n.created_at > agent_memories.created_at "
        "OR (n.created_at = agent_memories.created_at AND n.id > agent_memories.id)))"
    )
    op.create_index(
        "ux_agent_memories_in_use",
        "agent_memories",
        ["tenant_id", "team_id", "person", "agent_id", "key"],
        unique=True,
        postgresql_where=sa.text(IN_USE),
        mssql_where=sa.text(IN_USE),
    )
    op.add_column("memory_audit", sa.Column("team_id", sa.String(64)))

    op.create_table(
        "message_memory_use",
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("message_id", sa.String(64), nullable=False),
        sa.Column("memory_id", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(16), nullable=False),
        sa.Column("at", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "message_id", "memory_id", name="pk_message_memory_use"),
    )
    isolated = [_marked(), _marked("memory_audit")]
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, isolated, column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    if dialect == "postgresql":
        op.execute(f"GRANT SELECT, INSERT ON message_memory_use TO {TENANT_ROLE}")
    # memory_audit now has the team, so it carries the team policy in place of the tenant one, as 0077 did.
    for table in isolated:
        for statement in isolation_ddl(table, dialect, kind="team", chain=CHAIN):
            op.execute(statement)


def downgrade() -> None:
    # Migration tests step the chain below this revision and back up, so it must come off cleanly.
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "mssql"):
        for statement in isolation_ddl(_marked("memory_audit"), dialect, kind="tenant", chain=CHAIN):
            op.execute(statement)
    op.drop_table("message_memory_use")
    op.drop_column("memory_audit", "team_id")
    op.drop_index("ux_agent_memories_in_use", table_name="agent_memories")
    for column in reversed(_columns()):
        op.drop_column("agent_memories", column.name, mssql_drop_default=True)
