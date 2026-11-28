"""built-in grid: the watches area

A watched folder copies an app's folders into the team's Files for every member, so adding, changing, checking and
deleting one has a cell of its own, watches.manage, held by Admin and Builder (each holds every cell of its kind, as the
catalogue grants). Reading a watch follows files.view, so no role is given watches.view. Adds each missing cell and
raises each tenant's permission version, with the isolation policy of roles, role_permissions and tenants set aside
(`backfill_ddl`) so the writes see every tenant's rows; the downgrade removes the area's cells the same way.

Revision ID: 20261124_0100_watches_cells
Revises: 20261124_0100_close_invites
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from ops_store.schema import TENANT_SCOPED, backfill_ddl

revision = "20261124_0100_watches_cells"
down_revision = "20261124_0100_close_invites"
branch_labels = None
depends_on = None

EVERY = ("view", "create", "edit", "publish", "delete", "run", "decide", "manage")
CELLS = {"admin": EVERY, "builder": EVERY}
CHAIN = "platform"
RAISE = "UPDATE tenants SET permission_version = permission_version + 1"


def _key(name: str) -> sa.Column[str]:
    # `tenants` is isolated by its own key (ops_store.schema.tenant_column), every other table by tenant_id.
    return (
        sa.Column("id", sa.String(64), primary_key=True) if name == "tenants" else sa.Column("tenant_id", sa.String(64))
    )


def _set_aside() -> tuple[list[str], list[str]]:
    tables = [sa.Table(n, sa.MetaData(), _key(n), info=TENANT_SCOPED) for n in ("roles", "role_permissions", "tenants")]
    return backfill_ddl(tables, op.get_bind().dialect.name, chain=CHAIN, kind="tenant")


def upgrade() -> None:
    inserts = [
        "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
        f"SELECT r.tenant_id, r.id, 'watches', '{action}', 'all' FROM roles r WHERE r.id = '{role}' "
        "AND NOT EXISTS (SELECT 1 FROM role_permissions p WHERE p.tenant_id = r.tenant_id "
        f"AND p.role_id = r.id AND p.area = 'watches' AND p.action = '{action}')"
        for role, actions in CELLS.items()
        for action in actions
    ]
    before, after = _set_aside()
    for statement in (*before, *inserts, RAISE, *after):
        op.execute(statement)


def downgrade() -> None:
    before, after = _set_aside()
    for statement in (*before, "DELETE FROM role_permissions WHERE area = 'watches'", RAISE, *after):
        op.execute(statement)
