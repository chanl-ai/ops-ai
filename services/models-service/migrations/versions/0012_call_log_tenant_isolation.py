"""call_log_tenant_isolation: each tenant's model calls are held to that tenant

model_call_log holds a tenant's runs, threads, request hashes and the cost of each call, and was an install table
because a key's caps summed its rows across tenants. The caps now read model_key_spend, a key's spend and calls per
second, UTC day and run, whose day and run totals are set here from the call rows; a call that named no tenant moves
to model_call_refusals, which has no tenant column, in pages; then the log carries the generated tenant policy for
ops_models_tenant (models_0009). Plain SQL, so it renders offline; both steps are safe to re-run.

Revision ID: models_0012
Revises: models_0011
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.dialect import db_now
from ops_store.schema import TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "models_0012"
down_revision = "models_0011"
branch_labels = None
depends_on = None

CHAIN = "models"
ROLE = "ops_models_tenant"
MONEY = sa.Numeric(18, 6)
BATCH = 1000

CALL = [
    "id",
    "key_id",
    "alias",
    "alias_version",
    "provider_model",
    "input_tokens",
    "output_tokens",
    "cost",
    "latency_ms",
    "outcome",
    "reason",
    "sensitivity",
    "run_id",
    "step_id",
    "thread_id",
    "request_hash",
    "created_at",
    "images",
]


def _log() -> sa.Table:
    return sa.Table("model_call_log", sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def _call_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("key_id", sa.String(200), nullable=False),
        sa.Column("alias", sa.String(120), nullable=False),
        sa.Column("alias_version", sa.Integer),
        sa.Column("provider_model", sa.String(200)),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("cost", MONEY, nullable=False),
        sa.Column("latency_ms", sa.Integer, nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(64)),
        sa.Column("sensitivity", sa.String(16)),
        sa.Column("run_id", sa.String(64)),
        sa.Column("step_id", sa.String(200)),
        sa.Column("thread_id", sa.String(64)),
        sa.Column("request_hash", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=db_now()),
        sa.Column("images", sa.Integer, nullable=False, server_default="0"),
    ]


def backfill_sql(dialect: str) -> list[str]:
    """Sets each key's day and run totals from every call row, the log's and the refusals' (a call is in one of the
    two whether or not the move has run), so a re-run gives the same totals. A second's count is not backfilled: the
    rate window starts empty at the migration, for at most one minute."""
    calls = ", ".join(("key_id", "run_id", "cost", "created_at"))
    every = f"(SELECT {calls} FROM model_call_log UNION ALL SELECT {calls} FROM model_call_refusals) c"
    if dialect == "postgresql":
        day, join = "to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD')", "||"
    else:
        day, join = "CONVERT(char(10), SWITCHOFFSET(created_at, 0), 23)", "+"
    insert = "INSERT INTO model_key_spend (key_id, period, amount, calls, starts_at) SELECT key_id, "
    return [
        "DELETE FROM model_key_spend WHERE period LIKE 'day:%' OR period LIKE 'run:%'",
        f"{insert}'day:' {join} {day}, SUM(cost), COUNT(*), MIN(created_at) FROM {every} GROUP BY key_id, {day}",
        f"{insert}'run:' {join} run_id, SUM(cost), COUNT(*), MIN(created_at) FROM {every} "
        "WHERE run_id IS NOT NULL GROUP BY key_id, run_id",
    ]


def move_sql(dialect: str, source: str, target: str, which: str) -> str:
    """Moves the rows of `source` that `which` selects into `target`, a page at a time: a page is copied unless already
    there, then every copied row leaves `source`, so a stopped run leaves nothing lost and a re-run finishes it."""
    cols = ", ".join(CALL)
    absent = f"id NOT IN (SELECT id FROM {target})"
    leave = f"DELETE FROM {source} WHERE {which} AND id IN (SELECT id FROM {target})"
    if dialect == "postgresql":
        page = f"INSERT INTO {target} ({cols}) SELECT {cols} FROM {source} WHERE {which} AND {absent} LIMIT {BATCH}"
        return (
            f"DO $$ DECLARE moved integer; BEGIN LOOP {page}; {leave}; "
            "GET DIAGNOSTICS moved = ROW_COUNT; EXIT WHEN moved = 0; END LOOP; END $$"
        )
    page = f"INSERT INTO {target} ({cols}) SELECT TOP ({BATCH}) {cols} FROM {source} WHERE {which} AND {absent}"
    return f"WHILE 1 = 1 BEGIN {page}; {leave}; IF @@ROWCOUNT = 0 BREAK; END"


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    op.create_table("model_call_refusals", *_call_columns())
    op.create_index("ix_model_call_refusals_key_id", "model_call_refusals", ["key_id"])
    op.create_index("ix_model_call_refusals_thread_id", "model_call_refusals", ["thread_id"])
    op.create_index("ix_model_call_refusals_created_at", "model_call_refusals", ["created_at"])
    op.create_table(
        "model_key_spend",
        sa.Column("key_id", sa.String(200), primary_key=True),
        sa.Column("period", sa.String(80), primary_key=True),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("calls", sa.Integer, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Every read of the log names the tenant (the policy adds it) and the page sorts newest first.
    op.create_index("ix_model_call_log_tenant_created", "model_call_log", ["tenant_id", "created_at"])
    if dialect not in ("postgresql", "mssql"):
        return
    if dialect == "postgresql":
        op.execute("SET LOCAL row_security = off")
    for statement in backfill_sql(dialect):
        op.execute(statement)
    op.execute(move_sql(dialect, "model_call_log", "model_call_refusals", "tenant_id IS NULL"))
    if dialect == "postgresql":
        op.execute(f"GRANT SELECT, INSERT ON model_call_log TO {ROLE}")
    else:
        for statement in mssql_predicates_ddl(CHAIN, [_log()], column_type=_column_type, system_user=None):
            op.execute(statement)
    for statement in isolation_ddl(_log(), dialect, chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect in ("postgresql", "mssql"):
        for statement in isolation_drop_ddl(_log(), dialect):
            op.execute(statement)
    if dialect == "postgresql":
        op.execute(f"REVOKE ALL ON model_call_log FROM {ROLE}")
    if dialect in ("postgresql", "mssql"):
        op.execute(move_sql(dialect, "model_call_refusals", "model_call_log", "1 = 1"))
    op.drop_index("ix_model_call_log_tenant_created", table_name="model_call_log")
    op.drop_table("model_key_spend")
    op.drop_index("ix_model_call_refusals_created_at", table_name="model_call_refusals")
    op.drop_index("ix_model_call_refusals_thread_id", table_name="model_call_refusals")
    op.drop_index("ix_model_call_refusals_key_id", table_name="model_call_refusals")
    op.drop_table("model_call_refusals")
