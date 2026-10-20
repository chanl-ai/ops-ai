"""foreign keys that stay inside one tenant, and an audit table the tenant role can only append to

A single-column foreign key is checked without row-level security, so a row in tenant A could point at tenant B's
team or user. Each reference to a team or user now carries `tenant_id` too, against a unique (tenant_id, id) on the
parent; a null reference (an invited member, a tenant-level audit entry) is skipped by MATCH SIMPLE as before.

Revision ID: 0002_tenant_fks
Revises: 0001_identity
"""

from __future__ import annotations

from alembic import op

revision = "0002_tenant_fks"
down_revision = "0001_identity"
branch_labels = None
depends_on = None

ROLE = "ops_platform_tenant"

# (table, single-column constraint it replaces, columns, parent, new constraint)
REFERENCES = (
    ("members", "members_team_id_fkey", ["tenant_id", "team_id"], "teams", "fk_members_team"),
    ("members", "members_user_id_fkey", ["tenant_id", "user_id"], "users", "fk_members_user"),
    ("api_keys", "api_keys_team_id_fkey", ["tenant_id", "team_id"], "teams", "fk_api_keys_team"),
    ("api_keys", None, ["tenant_id", "created_by"], "users", "fk_api_keys_creator"),
    ("sessions", "sessions_user_id_fkey", ["tenant_id", "user_id"], "users", "fk_sessions_user"),
    ("audit_entries", None, ["tenant_id", "team_id"], "teams", "fk_audit_entries_team"),
)


def upgrade() -> None:
    op.create_unique_constraint("uq_teams_tenant_id", "teams", ["tenant_id", "id"])
    op.create_unique_constraint("uq_users_tenant_id", "users", ["tenant_id", "id"])
    for table, old, columns, parent, name in REFERENCES:
        if old is not None:
            op.drop_constraint(old, table, type_="foreignkey")
        op.create_foreign_key(name, table, parent, columns, ["tenant_id", "id"])
    # I7: entries are appended and read, never changed or removed, by tenant code.
    op.execute(f"REVOKE UPDATE, DELETE ON audit_entries FROM {ROLE}")


def downgrade() -> None:
    op.execute(f"GRANT UPDATE, DELETE ON audit_entries TO {ROLE}")
    for table, old, columns, parent, name in reversed(REFERENCES):
        op.drop_constraint(name, table, type_="foreignkey")
        if old is not None:
            op.create_foreign_key(old, table, parent, [columns[1]], ["id"])
    op.drop_constraint("uq_users_tenant_id", "users", type_="unique")
    op.drop_constraint("uq_teams_tenant_id", "teams", type_="unique")
