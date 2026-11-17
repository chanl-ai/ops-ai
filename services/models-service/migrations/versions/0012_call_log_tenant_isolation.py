"""call_log_tenant_isolation: each tenant's model calls are held to that tenant

model_call_log holds a tenant's runs, threads, request hashes and the cost of each call, and was an install table
because a key's caps summed its rows across tenants. The caps now read model_key_spend, a key's spend and calls per
second, UTC day and run, whose day and run totals are set here from the call rows; a call that named no tenant moves
to model_calls_untenanted, which has no tenant column, in one pass; then the log carries the generated tenant
policy for ops_models_tenant (models_0009). Plain SQL, so it renders offline; both steps are safe to re-run.

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
# A day or run idle this long is spend no cap reads again: not backfilled, and swept once it is
# (ops_models.store.tables.SPEND_KEPT_IDLE_S, the same value; a migration does not import the service).
KEPT_IDLE_S = 14 * 86400.0

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
    """Sets each key's spend today and on each run with a call inside KEPT_IDLE_S from every call row, the log's and
    the untenanted calls' (a call is in one of the two whether or not the move has run), so a re-run gives the same
    totals. A run still going keeps every call it made, however long ago it started; past days and idle runs are not
    written, as no cap reads them. A second's count is not backfilled: the rate window starts empty at the migration,
    for at most one minute."""
    calls = ", ".join(("key_id", "run_id", "cost", "created_at"))
    every = f"(SELECT {calls} FROM model_call_log UNION ALL SELECT {calls} FROM model_calls_untenanted) c"
    if dialect == "postgresql":
        day, join = "to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD')", "||"
        today = "date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'"
        since = f"now() - make_interval(secs => {KEPT_IDLE_S:g})"
        last = "EXTRACT(EPOCH FROM MAX(created_at))"
    else:
        day, join = "CONVERT(char(10), SWITCHOFFSET(created_at, 0), 23)", "+"
        today = "CAST(CAST(SYSUTCDATETIME() AS date) AS datetimeoffset)"
        since = f"DATEADD(second, -{KEPT_IDLE_S:.0f}, SYSDATETIMEOFFSET())"
        last = "CAST(DATEDIFF_BIG(millisecond, '1970-01-01T00:00:00+00:00', MAX(created_at)) AS float) / 1000"
    insert = "INSERT INTO model_key_spend (key_id, period, amount, calls, starts_at, last_call_s) SELECT key_id, "
    totals = f"SUM(cost), COUNT(*), MIN(created_at), {last}"
    return [
        "DELETE FROM model_key_spend WHERE period LIKE 'day:%' OR period LIKE 'run:%'",
        f"{insert}'day:' {join} {day}, {totals} FROM {every} WHERE created_at >= {today} GROUP BY key_id, {day}",
        f"{insert}'run:' {join} run_id, {totals} FROM {every} "
        f"WHERE run_id IS NOT NULL GROUP BY key_id, run_id HAVING MAX(created_at) >= {since}",
    ]


def move_sql(source: str, target: str, which: str) -> list[str]:
    """Moves the rows of `source` that `which` selects into `target`: one insert of every row not already there, then
    one delete of every row now there, each a single pass with no per-page rescan of `target`. The revision is one
    transaction, so a stopped run leaves nothing moved, and a re-run finds nothing left to move."""
    cols = ", ".join(CALL)
    there = f"EXISTS (SELECT 1 FROM {target} m WHERE m.id = {source}.id)"
    return [
        f"INSERT INTO {target} ({cols}) SELECT {cols} FROM {source} WHERE {which} AND NOT {there}",
        f"DELETE FROM {source} WHERE {which} AND {there}",
    ]


ALIAS_OUTCOME = {"ix_model_call_log_alias": "alias", "ix_model_call_log_outcome": "outcome"}


def _create_if_missing(name: str, column: str) -> None:
    """SQLAlchemy renders `if_not_exists` as plain CREATE INDEX on SQL Server, so the guard is written out there."""
    if op.get_context().dialect.name == "mssql":
        op.execute(
            f"IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = '{name}' "
            f"AND object_id = OBJECT_ID('model_call_log')) CREATE INDEX {name} ON model_call_log ({column})"
        )
    else:
        op.create_index(name, "model_call_log", [column], if_not_exists=True)


def upgrade() -> None:
    dialect = op.get_context().dialect.name
    # No call lands in the log while the spend is totalled and the tenant-less calls move: the step is one
    # transaction, so the lock holds to its end. models-service is stopped for it (docs/deploy/database.md).
    if dialect == "postgresql":
        op.execute("LOCK TABLE model_call_log IN EXCLUSIVE MODE")
    elif dialect == "mssql":
        op.execute("SELECT TOP (0) id FROM model_call_log WITH (TABLOCKX, HOLDLOCK)")
    op.create_table("model_calls_untenanted", *_call_columns())
    op.create_index("ix_model_calls_untenanted_key_id", "model_calls_untenanted", ["key_id"])
    op.create_index("ix_model_calls_untenanted_thread_id", "model_calls_untenanted", ["thread_id"])
    op.create_index("ix_model_calls_untenanted_created_at", "model_calls_untenanted", ["created_at"])
    op.create_table(
        "model_key_spend",
        sa.Column("key_id", sa.String(200), primary_key=True),
        sa.Column("period", sa.String(80), primary_key=True),
        sa.Column("amount", MONEY, nullable=False),
        sa.Column("calls", sa.Integer, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_call_s", sa.Float(asdecimal=False), nullable=False),
    )
    # Every read of the log names the tenant (the policy adds it) and the page sorts newest first.
    op.create_index("ix_model_call_log_tenant_created", "model_call_log", ["tenant_id", "created_at"])
    # The call list is searched and filtered on its alias and outcome. Guarded both ways, as a database that ran this
    # revision before it held these indexes has neither (models_0013 adds them there).
    for name, column in ALIAS_OUTCOME.items():
        _create_if_missing(name, column)
    if dialect not in ("postgresql", "mssql"):
        return
    # model_call_log is policed only at the end of this step, so the backfill reads every tenant's calls as the owner.
    for statement in backfill_sql(dialect):
        op.execute(statement)
    for statement in move_sql("model_call_log", "model_calls_untenanted", "tenant_id IS NULL"):
        op.execute(statement)
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
        for statement in move_sql("model_calls_untenanted", "model_call_log", "1 = 1"):
            op.execute(statement)
    for name in ALIAS_OUTCOME:
        op.drop_index(name, table_name="model_call_log", if_exists=True)
    op.drop_index("ix_model_call_log_tenant_created", table_name="model_call_log")
    op.drop_table("model_key_spend")
    op.drop_index("ix_model_calls_untenanted_created_at", table_name="model_calls_untenanted")
    op.drop_index("ix_model_calls_untenanted_thread_id", table_name="model_calls_untenanted")
    op.drop_index("ix_model_calls_untenanted_key_id", table_name="model_calls_untenanted")
    op.drop_table("model_calls_untenanted")
