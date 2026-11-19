"""The Channels list pages in SQL: a copy of platform's API keys and each version's watched mailbox

Revision ID: 0118_channel_list_columns
Revises: 0117_validation_list_columns

`GET /v1/channels` asked platform-service for every API key on each request and merged, filtered, counted and paged
mailboxes, embeds and keys in Python. Two things kept it there:

- The keys live in platform-service. `api_key_copies` (store/api_key_copies.py, `ops_store.copies`, team policy) holds
  what the list shows of each key, never its secret or hash. It starts empty and the worker's resync fills it from
  platform's `/v1/api-key-summaries`, then keeps it in step every minute and on each `api_key.changed` event.
- Which live workflows read a mailbox was worked out in Python from each definition's Email received trigger.
  engine_definitions gains `mailbox`, written with each version (ops_engine `definitions.watched_mailbox`), so the list
  joins mailboxes to the workflows that read them. Every version is filled here in plain SQL, so the revision renders
  as an offline script too: the first node of type `ops.trigger.email` names the mailbox in `parameters.mailbox` when
  that is a string of 1 to 320 characters, as `watched_mailbox` reads it. It runs inside the migration's transaction
  with the table's own policy set aside (on SQL Server it is dropped and made again before that transaction ends); on
  one UPDATE on each database (ops_store.dialect `json_first_match_text`). A stopped run writes the rest. The column
  is nullable (a workflow with no email trigger watches none) and has no default. Stop agents-service before upgrading
  (docs/deploy/database.md).

The down path drops the copy and its policy, then the column and its index. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_engine.store.definitions import EMAIL_TRIGGER, MAILBOX_MAX
from ops_store.dialect import json_first_match_text
from ops_store.schema import (
    TEAM_OWNED,
    TENANT_SCOPED,
    backfill_ddl,
    isolation_ddl,
    isolation_drop_ddl,
    mssql_predicates_ddl,
)

revision = "0118_channel_list_columns"
down_revision = "0117_validation_list_columns"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
COPY = "api_key_copies"
DEFINITIONS = "engine_definitions"


def _copy() -> sa.Table:
    """The copy as far as its policy needs, as of this revision."""
    return sa.Table(
        COPY,
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _definitions() -> sa.Table:
    """engine_definitions as far as the fill and its policy need, as of this revision."""
    return sa.Table(
        DEFINITIONS,
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("workflow_id", sa.String(64)),
        sa.Column("version", sa.Integer),
        sa.Column("definition", sa.JSON),
        sa.Column("mailbox", sa.String(320)),
        info=TENANT_SCOPED,
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _has_mailbox() -> bool:
    """Whether a stopped run already added it; offline SQL starts from 0117, where it is absent."""
    if op.get_context().as_sql:
        return False
    return "mailbox" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(DEFINITIONS)}


def _fill(t: sa.Table, dialect: str) -> None:
    """Writes every version's watched mailbox; a version that watches none keeps NULL."""
    found = json_first_match_text(
        dialect,
        t.c.definition,
        array="nodes",
        match_key="type",
        match=EMAIL_TRIGGER,
        path=("parameters", "mailbox"),
        max_length=MAILBOX_MAX,
    )
    op.execute(t.update().where(t.c.mailbox.is_(None)).values(mailbox=found))


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        COPY,
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("team_id", sa.String(64), primary_key=True),
        sa.Column("id", sa.String(200), primary_key=True),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.Float(), nullable=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("prefix", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("target_kind", sa.String(16), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("target_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("last_used_at", sa.String(40), nullable=True),
        sa.Column("expires_at", sa.String(40), nullable=True),
    )
    op.create_index("ix_api_key_copies_team_name", COPY, ["tenant_id", "team_id", "name"])
    if not _has_mailbox():
        with op.batch_alter_table(DEFINITIONS) as b:
            b.add_column(sa.Column("mailbox", sa.String(320), nullable=True))
        op.create_index("ix_engine_definitions_mailbox", DEFINITIONS, ["tenant_id", "mailbox"])
    t = _definitions()
    # Every tenant's versions are filled, so the table's own policy is set aside, only ever inside a transaction.
    before, after = backfill_ddl([t], dialect, chain=CHAIN, kind="tenant")
    for statement in before:
        op.execute(statement)
    _fill(t, dialect)
    for statement in after:
        op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    copy = _copy()
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [copy], column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    else:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {COPY} TO {TENANT_ROLE}")
    for statement in isolation_ddl(copy, dialect, kind="team", chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "mssql"):
        for statement in isolation_drop_ddl(_copy(), dialect):
            op.execute(statement)
    op.drop_index("ix_api_key_copies_team_name", table_name=COPY)
    op.drop_table(COPY)
    op.drop_index("ix_engine_definitions_mailbox", table_name=DEFINITIONS)
    with op.batch_alter_table(DEFINITIONS) as b:
        b.drop_column("mailbox")
