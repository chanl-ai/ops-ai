"""Hosted forms (c-535)

Revision ID: 0091_form_links
Revises: 0090_checkpointer_portable

A workflow's start form can be shared as a page of its own, by a signed link that expires or to the team's signed-in
members. form_links holds one row per form, in the team that shared it, with only the hash of the link's secret, and
carries the team policy like every team-owned table. A submission reserves its place under the form's daily cap as a
`started` trigger event, then names the run it started or turns into `start_failed` when the start raised, so the
runtime role may update those three columns of a trigger event and no other. Runs on PostgreSQL and SQL Server.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, isolation_ddl, mssql_predicates_ddl

revision = "0091_form_links"
down_revision = "0090_checkpointer_portable"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"


def _marked() -> sa.Table:
    return sa.Table(
        "form_links",
        sa.MetaData(),
        sa.Column("tenant_id", sa.String(64)),
        sa.Column("team_id", sa.String(64)),
        info={**TENANT_SCOPED, **TEAM_OWNED},
    )


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        "form_links",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("workflow_id", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False, server_default=""),
        sa.Column("after_text", sa.String(1000), nullable=False, server_default=""),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.String(40), nullable=False),
        sa.Column("daily_cap", sa.Integer(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("created_at", sa.String(32), nullable=False),
        sa.Column("rotated_at", sa.String(32)),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_form_links_slug"),
    )
    op.create_index("ix_form_links_workflow", "form_links", ["tenant_id", "workflow_id"])
    if dialect == "mssql":
        for statement in mssql_predicates_ddl(CHAIN, [_marked()], column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
    if dialect not in ("postgresql", "mssql"):
        return
    if dialect == "postgresql":
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON form_links TO {TENANT_ROLE}")
        op.execute(f"GRANT UPDATE (run_id, outcome, detail) ON trigger_events TO {TENANT_ROLE}")
    for statement in isolation_ddl(_marked(), dialect, kind="team", chain=CHAIN):
        op.execute(statement)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"REVOKE UPDATE (run_id, outcome, detail) ON trigger_events FROM {TENANT_ROLE}")
    op.drop_index("ix_form_links_workflow", table_name="form_links")
    op.drop_table("form_links")
