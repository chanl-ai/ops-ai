"""tenants, teams, users, members, api keys, sessions and audit entries, each under forced row-level security

Revision ID: 0001_identity
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_identity"
down_revision = None
branch_labels = None
depends_on = None

ROLE = "ops_platform_tenant"


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("allowed_domains", sa.JSON, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "teams",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("owner_groups", sa.JSON, nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_table(
        "members",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("team_id", sa.String(64), sa.ForeignKey("teams.id"), nullable=False, index=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id")),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("invite_token_hash", sa.String(64), unique=True),
        sa.Column("invite_expires_at", sa.String(40)),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("team_id", "email", name="uq_members_team_email"),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("team_id", sa.String(64), sa.ForeignKey("teams.id"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("prefix", sa.String(64), nullable=False, unique=True),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("scopes", sa.JSON, nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("last_used_at", sa.String(40)),
        sa.Column("revoked_at", sa.String(40)),
        sa.Column("disabled_at", sa.String(40)),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("auth_method", sa.String(16), nullable=False),
        sa.Column("refresh_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.String(40), nullable=False),
        sa.Column("revoked_at", sa.String(40)),
        sa.Column("last_seen_at", sa.String(40), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "audit_entries",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("team_id", sa.String(64), index=True),
        sa.Column("actor", sa.String(320), nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_kind", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("at", sa.String(40), nullable=False),
        sa.Column("detail", sa.JSON(none_as_null=True), nullable=False),
    )

    # Roles are cluster-wide, so another database's migration may have made it already.
    op.execute(f"DO $$ BEGIN CREATE ROLE {ROLE} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    for table, column in (
        ("tenants", "id"),
        ("teams", "tenant_id"),
        ("users", "tenant_id"),
        ("members", "tenant_id"),
        ("api_keys", "tenant_id"),
        ("sessions", "tenant_id"),
        ("audit_entries", "tenant_id"),
    ):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {ROLE}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE: the table owner is filtered too, so a deployment that connects as the owner is still guarded.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} "
            f"USING ({column} = current_setting('app.tenant_id', true)) "
            f"WITH CHECK ({column} = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    for table in ("audit_entries", "sessions", "api_keys", "members", "users", "teams", "tenants"):
        op.drop_table(table)
