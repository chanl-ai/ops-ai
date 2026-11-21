"""roles given to groups, and the team's approval rules as a cell of their own

Groups. `groups` holds a workspace's groups (kept by hand, or mirroring a sign-in provider's group by the value it
sends) and `group_members` who is in each; a role assignment may now name a group as its subject
(`role_assignments.subject_kind = 'group'`), so whoever is in the group holds the role where it is given. Both tables
are tenant-scoped like every platform table: forced row-level security on PostgreSQL, a security policy over the
chain's tenant predicates on SQL Server (made by 0042).

Approvals. The `approvals` area is added to the grid: the team's approval rules (`appChanges`, `appChangesByApp`,
`requesterMayDecide`) are changed by `approvals.manage` in the team, where `settings.manage` in the team changed them
before. Every role keeps what it could do: Admin takes every approvals cell (it holds every cell); Builder, Reviewer
and Viewer read the rules (`approvals.view`), as every member read the policies; and any other role that holds
`settings.manage` or `settings.view` takes the matching approvals cell at the same scope, so an edited built-in role
keeps the approval rules it could change. Security admin is left out: it is only ever held beside Admin, in the
Security team. Nothing is taken away, so no person loses access; each tenant's permission
version rises. Running it again adds nothing. Stored policy values are left as they are: a `requesterMayDecide`
stored as true still means on in every team and area.

The downgrade removes the approvals cells and every group's assignment, then the two tables.

Revision ID: 0046_roles_given_to_groups
Revises: 0045_api_key_revision
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from ops_store.schema import TENANT_SCOPED, isolation_ddl, isolation_drop_ddl

revision = "0046_roles_given_to_groups"
down_revision = "0045_api_key_revision"
branch_labels = None
depends_on = None

CHAIN = "platform"
TENANT = "ops_platform_tenant"
TABLES = ("groups", "group_members")
EVERY = ("view", "create", "edit", "publish", "delete", "run", "decide", "manage")
# The approvals cells each built-in role is seeded with (`ops_access.catalogue`), frozen at this revision.
SEEDED = {"admin": EVERY, "builder": ("view",), "reviewer": ("view",), "viewer": ("view",)}


def _add(select_role: str, action: str, scope: str) -> str:
    """Adds `approvals.<action>` to each role `select_role` names (rows of tenant_id, id), unless it has it."""
    return (
        "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
        f"SELECT r.tenant_id, r.id, 'approvals', '{action}', {scope} FROM ({select_role}) r "
        "WHERE NOT EXISTS (SELECT 1 FROM role_permissions p WHERE p.tenant_id = r.tenant_id "
        f"AND p.role_id = r.id AND p.area = 'approvals' AND p.action = '{action}')"
    )


def _marked(name: str) -> sa.Table:
    return sa.Table(name, sa.MetaData(), sa.Column("tenant_id", sa.String(64)), info=TENANT_SCOPED)


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    op.create_table(
        "groups",
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("provider_id", sa.String(64)),
        sa.Column("external_value", sa.String(255)),
        sa.Column("created_by", sa.String(320), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_groups_name"),
    )
    op.create_table(
        "group_members",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("group_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("added_by", sa.String(320), nullable=False),
        sa.Column("added_at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "group_id"],
            ["groups.tenant_id", "groups.id"],
            name="fk_group_members_group",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_group_members_user", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_group_members_user", "group_members", ["tenant_id", "user_id"])
    for role, actions in SEEDED.items():
        for action in actions:
            op.execute(_add(f"SELECT tenant_id, id FROM roles WHERE id = '{role}'", action, "'all'"))
    for action in ("manage", "view"):
        held = (
            "SELECT p.tenant_id, p.role_id AS id, p.scope FROM role_permissions p "
            f"WHERE p.area = 'settings' AND p.action = '{action}' AND p.role_id NOT IN ('admin', 'security_admin')"
        )
        op.execute(_add(held, action, "r.scope"))
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")
    if dialect == "postgresql":
        for name in TABLES:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {name} TO {TENANT}")
    if dialect in ("postgresql", "mssql"):
        for name in TABLES:
            for statement in isolation_ddl(_marked(name), dialect, chain=CHAIN):
                op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "mssql"):
        # A SQL Server security policy is schema-bound to its table: DROP TABLE is refused while it stands.
        for name in TABLES:
            for statement in isolation_drop_ddl(_marked(name), dialect):
                op.execute(statement)
    op.execute("DELETE FROM role_permissions WHERE area = 'approvals'")
    op.execute("DELETE FROM role_assignments WHERE subject_kind = 'group'")
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")
    op.drop_index("ix_group_members_user", table_name="group_members")
    op.drop_table("group_members")
    op.drop_table("groups")
