"""workflow_schedules: one saved schedule per workflow and trigger step, with the schedule clock's slot state

Revision ID: 20261123_1900_workflow_schedules
Revises: 20261124_0257_skill_owner_ids

Outside the workflow's versions, so a save applies at once (store/schedules.py). Tenant RLS as on poll_cursors (0045),
with team_id a plain column: a schedule is read and written through its workflow's own rights, which cover shared
workflows the team policy has no branch for. On SQL Server the table takes the chain's tenant security policy after it
is created and loses it before it is dropped, since SQL Server refuses to drop a table a policy is bound to. The
runtime role may delete, because clearing a schedule and deleting its
workflow remove the row, and may delete trigger_events, because the schedule clock drops its own rows after
KEEP_SCHEDULE_DAYS (store/trigger_events.py).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mssql

from ops_store.schema import TENANT_SCOPED, isolation_ddl, isolation_drop_ddl, mssql_predicates_ddl, role_ddl

revision = "20261123_1900_workflow_schedules"
down_revision = "20261124_0257_skill_owner_ids"
branch_labels = None
depends_on = None

CHAIN = "agents"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"
TABLE = "workflow_schedules"


def _marked() -> sa.Table:
    """The table as far as its policy needs, as of this revision."""
    return sa.Table(TABLE, sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=mssql.dialect())


def upgrade() -> None:
    op.create_table(
        "workflow_schedules",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("workflow_id", sa.String(64), primary_key=True),
        sa.Column("trigger_step", sa.String(100), primary_key=True),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("rule", sa.JSON, nullable=False),
        sa.Column("changed_by", sa.String(200), nullable=False),
        sa.Column("changed_by_name", sa.String(200), nullable=True),
        sa.Column("changed_at", sa.String(32), nullable=False),
        sa.Column("rule_digest", sa.String(64), nullable=True),
        sa.Column("last_slot_at", sa.String(32), nullable=True),
        sa.Column("last_outcome", sa.String(16), nullable=True),
        sa.Column("last_run_id", sa.String(64), nullable=True),
        sa.Column("seen_at", sa.String(32), nullable=True),
    )
    dialect = op.get_bind().dialect.name
    if dialect == "mssql":
        table = _marked()
        for statement in mssql_predicates_ddl(CHAIN, [table], column_type=_column_type, system_user=SYSTEM_ROLE):
            op.execute(statement)
        for statement in isolation_ddl(table, dialect, kind="tenant", chain=CHAIN):
            op.execute(statement)
    if dialect != "postgresql":
        return
    op.execute(role_ddl(TENANT_ROLE))
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON workflow_schedules TO {TENANT_ROLE}")
    op.execute("ALTER TABLE workflow_schedules ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE workflow_schedules FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY workflow_schedules_tenant ON workflow_schedules "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )
    op.execute(f"GRANT DELETE ON trigger_events TO {TENANT_ROLE}")
    # The grant is for the schedule clock's own rows: a restrictive policy leaves email trigger rows undeletable.
    op.execute(
        "CREATE POLICY trigger_events_schedule_delete ON trigger_events AS RESTRICTIVE FOR DELETE "
        "USING (source LIKE 'schedule:%')"
    )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "mssql":
        for statement in isolation_drop_ddl(_marked(), dialect):
            op.execute(statement)
    if dialect == "postgresql":
        op.execute("DROP POLICY IF EXISTS trigger_events_schedule_delete ON trigger_events")
        op.execute(f"REVOKE DELETE ON trigger_events FROM {TENANT_ROLE}")
        op.execute("DROP POLICY IF EXISTS workflow_schedules_tenant ON workflow_schedules")
    op.drop_table("workflow_schedules")
