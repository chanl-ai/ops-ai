"""write_approvals_on: every tool write saved since 2026-11-01 waits for approval, and each change is recorded

Writes saved on or after 1 November could hold requires_approval=false and then ran with nobody approving them. Each
such operation is set to true, and one entry in the shared audit log
(ops_store.audit, through service_outbox) names the tenant, module, operation and reason. The module's
updated_at is the save time of its writes. Earlier writes are left as their team set them. Only operations that change
get a row, so a second run changes and records nothing. Downgrade drops no data: the approvals stay on and the audit
rows stay, because turning approval back off would reopen the gap. An admin can still switch a write to false later;
this migration runs once and never re-applies.

Revision ID: tools_0072_write_approvals_on
Revises: tools_0071_account_key
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.util import await_only

from ops_store.audit import record
from ops_store.outbox import outbox_table

revision = "tools_0072_write_approvals_on"
down_revision = "tools_0071_account_key"
branch_labels = None
depends_on = None

# Timezone-aware: a naive value is read in the session's zone, which moved the cut-off by the zone's offset.
SINCE = datetime(2026, 11, 1, tzinfo=UTC)
REASON = "Writes saved since 1 November now wait for approval before they run."


def upgrade() -> None:
    ops = sa.table(
        "module_operations",
        sa.column("tenant_id", sa.String),
        sa.column("id", sa.String),
        sa.column("module_id", sa.String),
        sa.column("access", sa.String),
        sa.column("requires_approval", sa.Boolean),
    )
    modules = sa.table(
        "tool_modules",
        sa.column("tenant_id", sa.String),
        sa.column("id", sa.String),
        sa.column("team_id", sa.String),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    bind = op.get_bind()
    # The migration runs inside AsyncConnection.run_sync; the shared audit writer is async, so it is awaited on the
    # async proxy of this same connection and commits with the change.
    audit_conn = AsyncConnection._retrieve_proxy_for_target(bind)  # pyright: ignore[reportPrivateUsage]
    outbox = outbox_table(sa.MetaData())
    rows = bind.execute(
        sa.select(ops.c.tenant_id, modules.c.team_id, ops.c.module_id, ops.c.id)
        .select_from(
            ops.join(modules, sa.and_(modules.c.tenant_id == ops.c.tenant_id, modules.c.id == ops.c.module_id))
        )
        .where(ops.c.access == "write", ops.c.requires_approval.is_(False), modules.c.updated_at >= SINCE)
    ).all()
    for tenant, team, module, operation in rows:
        bind.execute(
            ops.update()
            .where(ops.c.tenant_id == tenant, ops.c.module_id == module, ops.c.id == operation)
            .values(requires_approval=True)
        )
        await_only(
            record(
                audit_conn,
                outbox,
                tenant_id=tenant,
                team_id=team,
                actor="system",
                action="tool.operation.requires_approval",
                target_kind="tool_operation",
                target_id=operation,
                summary=f"Writes of {module} now wait for approval ({operation}).",
                detail={"moduleId": module, "operationId": operation, "reason": REASON},
            )
        )


def downgrade() -> None:
    # Approvals and audit rows are kept: dropping the table would erase the record of what was changed.
    return
