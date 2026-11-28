"""Budgets, their reservations and the replay record move into the model gateway

A conversation's budget and the record that lets a crashed reply be repeated without paying again lived in the
agents service, so a model call from any other loop passed them. Three tenant-scoped tables hold them here, where every
call leaves: model_budgets (caps, spend and live reservations per budget), model_budget_reservations (one call's hold
on one budget until it settles) and model_replays (the provider's answer under a replay key). Each carries the
generated tenant policy for ops_models_tenant (models_0009). The downgrade drops them.

Revision ID: 20261126_1200_budgets_replays
Revises: 20261122_2017_list_sort_indexes
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.dialect import db_now
from ops_store.schema import TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl

revision = "20261126_1200_budgets_replays"
down_revision = "20261122_2017_list_sort_indexes"
branch_labels = None
depends_on = None

CHAIN = "models"
ROLE = "ops_models_tenant"
MONEY = sa.Numeric(18, 6)
TABLES = ("model_budgets", "model_budget_reservations", "model_replays")


def _scoped(name: str) -> sa.Table:
    return sa.Table(name, sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    op.create_table(
        "model_budgets",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("id", sa.String(200), primary_key=True),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("created_by", sa.String(80), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("parent_id", sa.String(200)),
        sa.Column("max_cost", MONEY),
        sa.Column("max_calls", sa.Integer),
        sa.Column("max_tokens", sa.BigInteger),
        sa.Column("spent_cost", MONEY, nullable=False, server_default="0"),
        sa.Column("spent_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("spent_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("reserved_cost", MONEY, nullable=False, server_default="0"),
        sa.Column("reserved_calls", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reserved_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("closing_keys", sa.JSON, nullable=False),
        sa.Column("check_calls", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=db_now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=db_now()),
    )
    op.create_index("ix_model_budgets_parent", "model_budgets", ["tenant_id", "parent_id"])
    op.create_table(
        "model_budget_reservations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("budget_id", sa.String(200), nullable=False),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("cost", MONEY, nullable=False),
        sa.Column("calls", sa.Integer, nullable=False),
        sa.Column("tokens", sa.BigInteger, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_budget_reservations_budget", "model_budget_reservations", ["tenant_id", "budget_id"])
    op.create_index("ix_model_budget_reservations_expires", "model_budget_reservations", ["expires_at"])
    op.create_table(
        "model_replays",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("replay_key", sa.String(240), primary_key=True),
        sa.Column("request_hash", sa.String(64), primary_key=True),
        sa.Column("response", sa.UnicodeText, nullable=False),
        sa.Column("call_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=db_now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_replays_expires", "model_replays", ["expires_at"])
    dialect = op.get_context().dialect.name
    scoped = [_scoped(name) for name in TABLES]
    if dialect == "postgresql":
        # The migrating role may own the tables; once FORCE is on, row-level security would hide rows from it.
        op.execute("SET LOCAL row_security = off")
        for name in TABLES:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO {ROLE}")
    elif dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, scoped, column_type=_column_type, system_user=None):
            op.execute(statement)
    else:
        return
    for table in scoped:
        for statement in isolation_ddl(table, dialect, chain=CHAIN):
            op.execute(statement)


def downgrade() -> None:
    dialect = op.get_context().dialect.name
    if dialect in ("postgresql", "mssql"):
        for name in TABLES:
            for statement in isolation_drop_ddl(_scoped(name), dialect):
                op.execute(statement)
    if dialect == "postgresql":
        for name in TABLES:
            op.execute(f"REVOKE ALL ON {name} FROM {ROLE}")
    op.drop_index("ix_model_replays_expires", table_name="model_replays")
    op.drop_table("model_replays")
    op.drop_index("ix_model_budget_reservations_expires", table_name="model_budget_reservations")
    op.drop_index("ix_model_budget_reservations_budget", table_name="model_budget_reservations")
    op.drop_table("model_budget_reservations")
    op.drop_index("ix_model_budgets_parent", table_name="model_budgets")
    op.drop_table("model_budgets")
