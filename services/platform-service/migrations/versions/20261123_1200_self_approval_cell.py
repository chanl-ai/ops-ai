"""roles: clear Approvals · decide from every role but Admin, before any code reads it

Approvals · decide becomes "approve own requests". No code checks the cell today, so a role may store it without it
meaning anything: every custom role copied from Admin does, and an edited built-in role may. Read as it is, those
roles' holders would approve their own requests the day the cell gains its meaning. This revision deletes the cell
from every role but Admin's, built-in or custom, writes one `role.self_approval` audit entry per role it clears (actor
`migration:<revision>`, the cell's scope in `before`), and raises each changed tenant's permission version once. A
second run finds nothing and writes nothing. The downgrade puts each cleared cell back from its audit entry.

Revision ID: 20261123_1200_self_approval_cell
Revises: 20261124_0100_close_invites
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import sqlalchemy as sa
from alembic import op

from ops_service_kit.ids import new_id, now_iso
from ops_store.schema import TENANT_SCOPED, backfill_ddl

revision = "20261123_1200_self_approval_cell"
down_revision = "20261124_0100_close_invites"
branch_labels = None
depends_on = None

ACTOR = f"migration:{revision}"
CELL = "approvals.decide"
POLICED = ("tenants", "roles", "role_permissions", "audit_entries")

audit_entries = sa.table(
    "audit_entries",
    sa.column("id", sa.String),
    sa.column("tenant_id", sa.String),
    sa.column("team_id", sa.String),
    sa.column("actor", sa.String),
    sa.column("action", sa.String),
    sa.column("target_kind", sa.String),
    sa.column("target_id", sa.String),
    sa.column("request_id", sa.String),
    sa.column("at", sa.String),
    sa.column("detail", sa.JSON),
)


def _policed(names: tuple[str, ...]) -> list[sa.Table]:
    md = sa.MetaData()
    key = {"tenants": sa.Column("id", sa.String(64), primary_key=True)}
    return [sa.Table(n, md, key.get(n, sa.Column("tenant_id", sa.String(64))), info=TENANT_SCOPED) for n in names]


def _every_tenant(c: sa.Connection, work: Callable[[sa.Connection], None]) -> None:
    """`work` over every tenant's rows. A deploy migrates with no tenant context, and on SQL Server the security
    policies show such a login no row, so without this the revision would find nothing and change nothing; each policed
    table's policy is set aside for the transaction and put back (`backfill_ddl`)."""
    before, after = backfill_ddl(_policed(POLICED), c.dialect.name, chain="platform", kind="tenant")
    for statement in before:
        c.execute(sa.text(statement))
    work(c)
    for statement in after:
        c.execute(sa.text(statement))


def clear(c: sa.Connection) -> None:
    """Every role but Admin loses the cell, each with its audit entry; a tenant's version rises once."""
    _every_tenant(c, _clear)


def _clear(c: sa.Connection) -> None:
    held = c.execute(
        sa.text(
            "SELECT tenant_id, role_id, scope FROM role_permissions "
            "WHERE area = 'approvals' AND action = 'decide' AND role_id <> 'admin'"
        )
    ).all()
    if not held:
        return
    at = now_iso()
    c.execute(
        audit_entries.insert(),
        [
            {
                "id": new_id("aud"),
                "tenant_id": tenant,
                "team_id": None,
                "actor": ACTOR,
                "action": "role.self_approval",
                "target_kind": "role",
                "target_id": role,
                "request_id": ACTOR[:64],
                "at": at,
                "detail": {"changed": [CELL], "before": {CELL: scope}, "after": {CELL: None}},
            }
            for tenant, role, scope in held
        ],
    )
    c.execute(
        sa.text("DELETE FROM role_permissions WHERE area = 'approvals' AND action = 'decide' AND role_id <> 'admin'")
    )
    for tenant in sorted({t for t, _, _ in held}):
        c.execute(
            sa.text("UPDATE tenants SET permission_version = permission_version + 1 WHERE id = :t"), {"t": tenant}
        )


def upgrade() -> None:
    clear(op.get_bind())


def downgrade() -> None:
    """Each cell this revision cleared goes back with the scope its audit entry names, where the role still exists
    and holds no such cell; the audit entries stay, since the audit log is append-only."""
    _every_tenant(op.get_bind(), _put_back)


def _put_back(c: sa.Connection) -> None:
    rows = c.execute(
        sa.text(
            "SELECT tenant_id, target_id, detail FROM audit_entries WHERE actor = :a AND action = 'role.self_approval'"
        ),
        {"a": ACTOR},
    ).all()
    tenants: set[str] = set()
    for tenant, role, detail in rows:
        held: dict[str, Any] = json.loads(detail) if isinstance(detail, str) else dict(detail)
        scope = held.get("before", {}).get(CELL)
        exists = c.execute(
            sa.text(
                "SELECT (SELECT COUNT(*) FROM roles WHERE tenant_id = :t AND id = :r), "
                "(SELECT COUNT(*) FROM role_permissions WHERE tenant_id = :t AND role_id = :r "
                "AND area = 'approvals' AND action = 'decide')"
            ),
            {"t": tenant, "r": role},
        ).one()
        if scope and exists[0] and not exists[1]:
            c.execute(
                sa.text(
                    "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
                    "VALUES (:t, :r, 'approvals', 'decide', :s)"
                ),
                {"t": tenant, "r": role, "s": scope},
            )
            tenants.add(tenant)
    for tenant in sorted(tenants):
        c.execute(
            sa.text("UPDATE tenants SET permission_version = permission_version + 1 WHERE id = :t"), {"t": tenant}
        )
