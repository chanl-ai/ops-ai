"""write_approvals_on: a stored requires_approval=false becomes not set (NULL), so the team default decides

requires_approval is nullable: NULL follows the team default (a write waits unless the team lets its app change
without asking), true waits, false runs at once. Offs saved before 1 November were kept and new tools stored off, so
every stored false on a write, at any date, is set to NULL, and one entry in the shared audit log
(ops_store.audit, through service_outbox) names the tenant, module, operation and reason. Only operations that change
get a row, so a second run changes and records nothing. Downgrade drops no data: the column stays nullable and the
audit rows stay. An admin can still switch a write to false later; this migration runs once and never re-applies.

Revision ID: tools_0072_write_approvals_on
Revises: tools_0071_account_key
"""

from __future__ import annotations

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

REASON = "The approval setting is now not set, so the team default decides whether this write waits."


def upgrade() -> None:
    op.alter_column("module_operations", "requires_approval", existing_type=sa.Boolean(), nullable=True)
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
        .where(ops.c.access == "write", ops.c.requires_approval.is_(False))
    ).all()
    for tenant, team, module, operation in rows:
        bind.execute(
            ops.update()
            .where(ops.c.tenant_id == tenant, ops.c.module_id == module, ops.c.id == operation)
            .values(requires_approval=None)
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
                summary=f"{operation} of {module} follows the team default for approval.",
                detail={"moduleId": module, "operationId": operation, "reason": REASON},
            )
        )


def downgrade() -> None:
    # The column stays nullable and the audit rows stay: restoring false would erase the record of what was changed.
    return
