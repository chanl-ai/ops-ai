"""roles, their permissions and who holds them, seeded so every member keeps exactly today's access

Creates `roles`, `role_permissions` and `role_assignments` under the same forced row-level security as 0001, and
`tenants.permission_version`. Then, per tenant, writes the six built-in roles with the grid below, and gives every
active member the built-in role their `members.role` names in that team; an admin of the Security team
(`Settings.security_team_id`) also gets Security admin there. The grid and the mapping are copied here from
`ops_platform/permissions.py` as they stood at this revision, because a migration that has run never changes;
`tests/test_role_migration.py` checks the copy against the module.

The data step reads every tenant's rows, so it runs as the database owner with row-level security bypassed, as the
compose superuser is. A role without BYPASSRLS would see no tenant and seed nothing, leaving every member with no role,
so on PostgreSQL the migration refuses to start under one.

Revision ID: 0006_roles
Revises: 0005_lookup_paths
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.settings import Settings

revision = "0006_roles"
down_revision = "0005_lookup_paths"
branch_labels = None
depends_on = None

ROLE = "ops_platform_tenant"
GRANTED_BY = "migration:0006_roles"

# role id: (name, description, "area:action,action[@own] ...")
BUILTIN = {
    "admin": (
        "Admin",
        "Everything a builder and a reviewer do in the team, plus its people, API keys and audit log.",
        "agents:view,create,edit,publish,delete,run,decide workflows:view,create,edit,publish,delete,run,decide "
        "skills:view,create,edit,publish,delete,decide guardrails:view,create,edit,publish,delete,decide "
        "widgets:view,create,edit,publish,delete,decide knowledge:view,create,edit,delete "
        "tools:view,create,edit,publish,delete,run,decide secrets_egress:view files:view,create,delete,manage "
        "chat:view,run,decide reviews:view,decide cases:view,manage deployments:view,create,edit,delete "
        "access:view,create,edit,delete,manage audit:view",
    ),
    "builder": (
        "Builder",
        "Reads the team's work, and creates, edits, tests and publishes its definitions.",
        "agents:view,create,edit,publish,delete,run workflows:view,create,edit,publish,delete,run "
        "skills:view,create,edit,publish skills:delete@own guardrails:view,create,edit,publish guardrails:delete@own "
        "widgets:view,create,edit,publish,delete knowledge:view,create knowledge:edit,delete@own "
        "tools:view,create,edit,publish,delete,run secrets_egress:view files:view,create,delete chat:view,run "
        "reviews:view cases:view cases:manage@own deployments:view,create,edit,delete access:view",
    ),
    "reviewer": (
        "Reviewer",
        "Reads the team's work and decides its reviews; in the Security team, decides module security reviews.",
        "agents:view,decide workflows:view,decide skills:view,decide skills:delete@own guardrails:view,decide "
        "guardrails:delete@own widgets:view,decide knowledge:view tools:view,decide secrets_egress:view,decide "
        "files:view,create,delete chat:view,run,decide reviews:view,decide cases:view,manage deployments:view "
        "access:view",
    ),
    "viewer": (
        "Viewer",
        "Reads the team's work and chats with its agents.",
        "agents:view workflows:view skills:view skills:delete@own guardrails:view guardrails:delete@own widgets:view "
        "knowledge:view tools:view secrets_egress:view files:view,create,delete chat:view,run reviews:view cases:view "
        "cases:manage@own deployments:view access:view",
    ),
    "security_admin": (
        "Security admin",
        "Changes egress, secrets and storage settings for every team, and decides module security reviews.",
        "secrets_egress:view,create,edit,delete,decide,manage settings:view,manage",
    ),
    "chat_user": (
        "Chat user",
        "Chats with the agents published to the team and sees only their own threads; nothing else.",
        "chat:view@own chat:run",
    ),
}
MEMBER_ROLE = {"admin": "admin", "builder": "builder", "approver": "reviewer", "viewer": "viewer"}
TABLES = ("roles", "role_permissions", "role_assignments")


def grants(text: str) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for part in text.split():
        area, _, rest = part.partition(":")
        actions, _, own = rest.partition("@")
        out += [(area, action, "own" if own else "all") for action in actions.split(",")]
    return out


def _require_bypass() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    can_bypass = bind.execute(
        sa.text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
    ).scalar()
    if not can_bypass:
        user = bind.execute(sa.text("SELECT current_user")).scalar()
        raise RuntimeError(
            f"Migration 0006 seeds every tenant's roles and must run as a role with BYPASSRLS (or a superuser); "
            f"{user} has neither, so it would seed nothing and leave every member without a role."
        )


def upgrade() -> None:
    _require_bypass()
    op.add_column("tenants", sa.Column("permission_version", sa.Integer, nullable=False, server_default="1"))
    op.create_table(
        "roles",
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("builtin", sa.Boolean, nullable=False),
        sa.Column("description", sa.String(500), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "role_permissions",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("role_id", sa.String(64), primary_key=True),
        sa.Column("area", sa.String(32), primary_key=True),
        sa.Column("action", sa.String(16), primary_key=True),
        sa.Column("scope", sa.String(8), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"], name="fk_role_permissions_role"
        ),
    )
    op.create_table(
        "role_assignments",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("subject_kind", sa.String(8), nullable=False),
        sa.Column("subject_id", sa.String(64), nullable=False),
        sa.Column("role_id", sa.String(64), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.String(40)),
        sa.Column("granted_by", sa.String(320), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "subject_kind", "subject_id", "role_id", "team_id", name="uq_role_assignments"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"], name="fk_role_assignments_role"
        ),
    )
    op.create_index("ix_role_assignments_subject", "role_assignments", ["tenant_id", "subject_id"])

    if op.get_bind().dialect.name == "postgresql":
        for table in TABLES:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {ROLE}")
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
            op.execute(
                f"CREATE POLICY {table}_tenant ON {table} "
                "USING (tenant_id = current_setting('app.tenant_id', true)) "
                "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
            )
    _seed(Settings().security_team_id)


def _seed(security_team: str) -> None:
    bind = op.get_bind()
    now = now_iso()
    roles = sa.table(
        "roles",
        sa.column("tenant_id"),
        sa.column("id"),
        sa.column("name"),
        sa.column("builtin"),
        sa.column("description"),
        sa.column("created_at"),
    )
    perms = sa.table(
        "role_permissions", sa.column("tenant_id"), sa.column("role_id"), sa.column("area"), sa.column("action"),
        sa.column("scope"),
    )  # fmt: skip
    assignments = sa.table(
        "role_assignments",
        sa.column("id"),
        sa.column("tenant_id"),
        sa.column("subject_kind"),
        sa.column("subject_id"),
        sa.column("role_id"),
        sa.column("team_id"),
        sa.column("granted_by"),
        sa.column("reason"),
        sa.column("source"),
        sa.column("created_at"),
    )
    tenants = [str(t) for t in bind.execute(sa.text("SELECT id FROM tenants")).scalars()]
    for tenant in tenants:
        for role_id, (name, description, grid) in BUILTIN.items():
            bind.execute(
                roles.insert().values(
                    tenant_id=tenant, id=role_id, name=name, builtin=True, description=description, created_at=now
                )
            )
            bind.execute(
                perms.insert(),
                [
                    {"tenant_id": tenant, "role_id": role_id, "area": a, "action": x, "scope": s}
                    for a, x, s in grants(grid)
                ],
            )
    held = bind.execute(
        sa.text("SELECT tenant_id, team_id, user_id, role FROM members WHERE status = 'active' AND user_id IS NOT NULL")
    ).all()
    rows: list[dict[str, str]] = []
    for tenant, team, user, member_role in held:
        builtin = MEMBER_ROLE.get(str(member_role))
        if builtin is None:
            continue
        given = [builtin, "security_admin"] if team == security_team and builtin == "admin" else [builtin]
        rows += [
            {
                "id": new_id("ras"),
                "tenant_id": str(tenant),
                "subject_kind": "person",
                "subject_id": str(user),
                "role_id": role_id,
                "team_id": str(team),
                "granted_by": GRANTED_BY,
                "reason": f"Team membership as {member_role}",
                "source": "membership",
                "created_at": now,
            }
            for role_id in given
        ]
    if rows:
        bind.execute(assignments.insert(), rows)


def downgrade() -> None:
    op.drop_index("ix_role_assignments_subject", table_name="role_assignments")
    for table in reversed(TABLES):
        op.drop_table(table)
    op.drop_column("tenants", "permission_version")
