"""`install.manage` on every workspace's Owner role: the install admin changes the model aliases

The access catalogue gains the area `install` with one cell, `install.manage`, held only by the built-in role Owner:
one install serves one account, and model aliases apply to the whole install, so only its first admin (the
workspace's owner) creates or re-points them. A role's stored rows decide over its seed (`effective_grids`), so
each existing Owner role gets the row here; a workspace made later is seeded from the catalogue. Every table it reads
or writes has its isolation policy set aside (`backfill_ddl`) so it sees every tenant's rows, and each tenant's
permission version rises so the next request reads the new cell. Running it again adds nothing. The downgrade
removes the row: the code before this revision refuses a cell outside its catalogue.

Revision ID: 20261125_1300_install_owner
Revises: 20261124_0100_close_invites
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from ops_store.schema import TENANT_SCOPED, backfill_ddl

revision = "20261125_1300_install_owner"
down_revision = "20261124_0100_close_invites"
branch_labels = None
depends_on = None

CHAIN = "platform"

ADD = (
    "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
    "SELECT r.tenant_id, r.id, 'install', 'manage', 'all' FROM roles r WHERE r.id = 'owner' "
    "AND NOT EXISTS (SELECT 1 FROM role_permissions p WHERE p.tenant_id = r.tenant_id "
    "AND p.role_id = r.id AND p.area = 'install' AND p.action = 'manage')"
)
REMOVE = "DELETE FROM role_permissions WHERE area = 'install'"
BUMP = "UPDATE tenants SET permission_version = permission_version + 1"


def _policed() -> list[sa.Table]:
    return [
        sa.Table(name, sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)
        for name in ("roles", "role_permissions", "tenants")
    ]


def _run(*statements: str) -> None:
    before, after = backfill_ddl(_policed(), op.get_bind().dialect.name, chain=CHAIN, kind="tenant")
    for statement in (*before, *statements, *after):
        op.execute(statement)


def upgrade() -> None:
    _run(ADD, BUMP)


def downgrade() -> None:
    _run(REMOVE, BUMP)
