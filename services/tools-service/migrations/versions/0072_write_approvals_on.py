"""write_approvals_on: every tool write saved since 2026-11-01 waits for approval, and each change is recorded

Writes saved on or after 1 November could hold requires_approval=false and then ran with nobody approving them. Each
such operation is set to true, and one operation_audit row names the tenant, module, operation and reason. The module's
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

revision = "tools_0072_write_approvals_on"
down_revision = "tools_0071_account_key"
branch_labels = None
depends_on = None

SINCE = datetime(2026, 11, 1)
REASON = "Writes saved since 1 November now wait for approval before they run."


def upgrade() -> None:
    # Downgrade keeps the table, so a re-run finds it already there.
    exists = sa.inspect(op.get_bind()).has_table("operation_audit")
    audit_columns = (
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("module_id", sa.String(200), nullable=False),
        sa.Column("operation_id", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "module_id", "operation_id", "created_at"),
    )
    if exists:
        audit = sa.table("operation_audit", *(sa.column(c.name) for c in audit_columns if isinstance(c, sa.Column)))
    else:
        audit = op.create_table("operation_audit", *audit_columns)
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
        sa.column("updated_at", sa.DateTime),
    )
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(ops.c.tenant_id, ops.c.module_id, ops.c.id)
        .select_from(
            ops.join(modules, sa.and_(modules.c.tenant_id == ops.c.tenant_id, modules.c.id == ops.c.module_id))
        )
        .where(ops.c.access == "write", ops.c.requires_approval.is_(False), modules.c.updated_at >= SINCE)
    ).all()
    now = datetime.now(UTC).replace(tzinfo=None)
    for tenant, module, operation in rows:
        bind.execute(
            ops.update()
            .where(ops.c.tenant_id == tenant, ops.c.module_id == module, ops.c.id == operation)
            .values(requires_approval=True)
        )
        bind.execute(
            audit.insert().values(
                tenant_id=tenant, module_id=module, operation_id=operation, reason=REASON, created_at=now
            )
        )


def downgrade() -> None:
    # Approvals and audit rows are kept: dropping the table would erase the record of what was changed.
    return
