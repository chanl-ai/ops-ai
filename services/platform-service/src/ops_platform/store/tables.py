"""platform-service's tables, in its own migration chain (`alembic_version_platform`).

Every table carries `tenant_id` (the tenants table is keyed by it), and row-level security keeps each tenant's rows
from every other (migration 0001). An invited member is a `members` row with status `invited` and a hashed invite
token; it has no user until the invite is accepted. Secrets (API keys, refresh and invite tokens) are stored only as
SHA-256 hashes. Every reference to a team or user carries `tenant_id` too (migration 0002), because a foreign key is
checked without row-level security. Audit entries are append only: the tenant role may not update or delete them.
`team_id` is null for tenant-level events such as sign-in.
"""

from __future__ import annotations

import sqlalchemy as sa

metadata = sa.MetaData()

tenants = sa.Table(
    "tenants",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),  # active | suspended
    # Email domains an invite may be accepted from; empty means any.
    sa.Column("allowed_domains", sa.JSON, nullable=False),
    sa.Column("created_at", sa.String(40), nullable=False),
)

teams = sa.Table(
    "teams",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("owner_groups", sa.JSON, nullable=False),
    sa.Column("scope", sa.String(16), nullable=False),  # all | owned
    sa.Column("created_at", sa.String(40), nullable=False),
    sa.UniqueConstraint("tenant_id", "id", name="uq_teams_tenant_id"),
)

users = sa.Table(
    "users",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
    sa.Column("email", sa.String(320), nullable=False),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),  # active | suspended
    sa.Column("created_at", sa.String(40), nullable=False),
    sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    sa.UniqueConstraint("tenant_id", "id", name="uq_users_tenant_id"),
)

members = sa.Table(
    "members",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
    sa.Column("team_id", sa.String(64), nullable=False, index=True),
    sa.Column("user_id", sa.String(64)),  # null while invited
    sa.Column("email", sa.String(320), nullable=False),
    sa.Column("role", sa.String(16), nullable=False),  # admin | builder | approver | viewer
    sa.Column("status", sa.String(16), nullable=False),  # active | invited | removed
    sa.Column("invite_token_hash", sa.String(64), unique=True),
    sa.Column("invite_expires_at", sa.String(40)),
    sa.Column("created_at", sa.String(40), nullable=False),
    sa.Column("updated_at", sa.String(40), nullable=False),
    sa.UniqueConstraint("team_id", "email", name="uq_members_team_email"),
    sa.ForeignKeyConstraint(["tenant_id", "team_id"], ["teams.tenant_id", "teams.id"], name="fk_members_team"),
    sa.ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_members_user"),
)

api_keys = sa.Table(
    "api_keys",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
    sa.Column("team_id", sa.String(64), nullable=False, index=True),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("prefix", sa.String(64), nullable=False, unique=True),  # the key's id, looked up before the hash
    sa.Column("secret_hash", sa.String(64), nullable=False),
    sa.Column("scopes", sa.JSON, nullable=False),  # read | write
    sa.Column("created_by", sa.String(64), nullable=False),
    sa.Column("created_at", sa.String(40), nullable=False),
    sa.Column("last_used_at", sa.String(40)),
    sa.Column("revoked_at", sa.String(40)),
    # Set when the creator leaves the team or is suspended (I10); a disabled key verifies as revoked.
    sa.Column("disabled_at", sa.String(40)),
    sa.Column("expires_at", sa.String(40)),  # null: the key does not expire
    sa.ForeignKeyConstraint(["tenant_id", "team_id"], ["teams.tenant_id", "teams.id"], name="fk_api_keys_team"),
    sa.ForeignKeyConstraint(["tenant_id", "created_by"], ["users.tenant_id", "users.id"], name="fk_api_keys_creator"),
)

sessions = sa.Table(
    "sessions",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
    sa.Column("user_id", sa.String(64), nullable=False, index=True),
    sa.Column("auth_method", sa.String(16), nullable=False),  # dev | session
    # Rotated on every refresh; presenting an earlier one revokes the session.
    sa.Column("refresh_hash", sa.String(64), nullable=False, unique=True),
    sa.Column("expires_at", sa.String(40), nullable=False),
    sa.Column("revoked_at", sa.String(40)),
    sa.Column("last_seen_at", sa.String(40), nullable=False),
    sa.Column("created_at", sa.String(40), nullable=False),
    sa.ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_sessions_user"),
)

audit_entries = sa.Table(
    "audit_entries",
    metadata,
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
    sa.ForeignKeyConstraint(["tenant_id", "team_id"], ["teams.tenant_id", "teams.id"], name="fk_audit_entries_team"),
)

TENANT_TABLES = (teams, users, members, api_keys, sessions, audit_entries)
