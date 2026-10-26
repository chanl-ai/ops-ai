"""the workspace owner: built-in role Owner, its one cell, the backfilled owner and the closed-workspace columns

c-529 (owner, 2026-10-23): the access catalogue gains the area `workspace` with one cell, `workspace.manage`, held only
by the new built-in role Owner; Admin's every-cell grid leaves the area out. Each tenant gets the role and its grid
row, and the earliest person holding Admin in every team (`*`) becomes its owner; a tenant with no such person has
none. A partial unique index keeps one Owner assignment per tenant.

A closed workspace records when and by whom (`tenants.closed_at`, `closed_by`); its status is `closed`, then `purging`
once the purge starts. `platform_purge_due` finds the workspaces closed before a cutoff for the purge loop: it runs
before any tenant is chosen, so it is a SECURITY DEFINER lookup like those of migration 0004, returning tenant ids
only.

Revision ID: 0026_workspace_owner
Revises: 0025_connections_cells
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_workspace_owner"
down_revision = "0025_connections_cells"
branch_labels = None
depends_on = None

TENANT = "ops_platform_tenant"
LOOKUP = "ops_platform_lookup"
PURGE_DUE = "platform_purge_due(p_cutoff text)"
DESCRIPTION = "Transfers, closes and restores the workspace. One person holds it, and only a transfer moves it."


def upgrade() -> None:
    op.add_column("tenants", sa.Column("closed_at", sa.String(40)))
    op.add_column("tenants", sa.Column("closed_by", sa.String(64)))
    op.execute(
        "INSERT INTO roles (tenant_id, id, name, builtin, description, created_at) "
        f"SELECT t.id, 'owner', 'Owner', true, '{DESCRIPTION}', t.created_at FROM tenants t "
        "WHERE NOT EXISTS (SELECT 1 FROM roles r WHERE r.tenant_id = t.id AND r.id = 'owner')"
    )
    op.execute(
        "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
        "SELECT r.tenant_id, r.id, 'workspace', 'manage', 'all' FROM roles r WHERE r.id = 'owner' "
        "AND NOT EXISTS (SELECT 1 FROM role_permissions p WHERE p.tenant_id = r.tenant_id "
        "AND p.role_id = r.id AND p.area = 'workspace' AND p.action = 'manage')"
    )
    op.execute(
        "INSERT INTO role_assignments "
        "(id, tenant_id, subject_kind, subject_id, role_id, team_id, granted_by, reason, source, created_at) "
        "SELECT 'ras_' || substr(md5(a.tenant_id || '/owner'), 1, 24), a.tenant_id, 'person', a.subject_id, 'owner', "
        "'*', 'migration', 'The workspace''s first account admin', 'grant', a.created_at "
        "FROM (SELECT DISTINCT ON (tenant_id) tenant_id, subject_id, created_at FROM role_assignments "
        "WHERE role_id = 'admin' AND team_id = '*' AND subject_kind = 'person' "
        "ORDER BY tenant_id, created_at, id) a "
        "WHERE NOT EXISTS (SELECT 1 FROM role_assignments o WHERE o.tenant_id = a.tenant_id AND o.role_id = 'owner')"
    )
    op.create_index(
        "ux_role_assignments_owner",
        "role_assignments",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("role_id = 'owner'"),
        mssql_where=sa.text("role_id = 'owner'"),
        sqlite_where=sa.text("role_id = 'owner'"),
    )
    op.execute(
        f"CREATE FUNCTION {PURGE_DUE} RETURNS TABLE (tenant_id varchar) "
        "AS $$ SELECT t.id FROM public.tenants t WHERE t.status = 'closed' AND t.closed_at <= p_cutoff $$ "
        "LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp"
    )
    op.execute(f"ALTER FUNCTION {PURGE_DUE} OWNER TO {LOOKUP}")
    op.execute(f"REVOKE ALL ON FUNCTION {PURGE_DUE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {PURGE_DUE} TO {TENANT}")
    op.execute("UPDATE tenants SET permission_version = permission_version + 1")


def downgrade() -> None:
    op.execute(f"DROP FUNCTION {PURGE_DUE}")
    op.drop_index("ux_role_assignments_owner", table_name="role_assignments")
    op.execute("DELETE FROM role_assignments WHERE role_id = 'owner'")
    op.execute("DELETE FROM role_permissions WHERE role_id = 'owner'")
    op.execute("DELETE FROM roles WHERE id = 'owner'")
    op.drop_column("tenants", "closed_by")
    op.drop_column("tenants", "closed_at")
