"""platform-service's tables, in its own migration chain (`alembic_version_platform`).

Every table carries `tenant_id` (the tenants table is keyed by it), and row-level security keeps each tenant's rows
from every other (migration 0001). An invited member is a `members` row with status `invited` and a hashed invite
token; it has no user until the invite is accepted. Secrets (API keys, refresh and invite tokens) are stored only as
SHA-256 hashes. Every reference to a team or user carries `tenant_id` too (migration 0002), because a foreign key is
checked without row-level security. Audit entries are append only: the tenant role may not update or delete them.
`team_id` is null for tenant-level events such as sign-in.

Roles are data (migration 0006): `roles` holds the five built-in roles per tenant and any custom ones,
`role_permissions` one row per (area, action) a role grants with scope `all` or `own`, and `role_assignments` who holds
which role in which team. An assignment's subject is a person or a team (`subject_kind`, `subject_id`), and its
`team_id` is the team it applies in or `*` for every team the subject belongs to; both are never null so the unique
index dedupes on every database. `tenants.permission_version` rises with every change to any of these or to a
membership, and the platform token carries it so services can cache what a person may do.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine.default import DefaultExecutionContext

from ops_access import OWNER
from ops_store.schema import TENANT_SCOPED

metadata = sa.MetaData()


def _name_key(context: DefaultExecutionContext) -> str:
    """An insert that names a team and no key gets the lower-case name (seeds and tests write teams directly)."""
    return str(context.get_current_parameters()["name"]).lower()


tenants = sa.Table(
    "tenants",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("name", sa.String(200), nullable=False),
    # active | suspended | closed (its owner deleted it, restorable for the window) | purging | purged (c-529)
    sa.Column("status", sa.String(16), nullable=False),
    # Email domains an invite may be accepted from; empty means any.
    sa.Column("allowed_domains", sa.JSON, nullable=False),
    sa.Column("created_at", sa.String(40), nullable=False),
    sa.Column("permission_version", sa.Integer, nullable=False, server_default="1"),
    # Migration 0014 (c-202): the workspace's security team (null: Settings.security_team_id) and the team new people
    # join when nothing else names one (null: none).
    sa.Column("security_team_id", sa.String(64)),
    sa.Column("default_team_id", sa.String(64)),
    # Migration 0026 (c-529): when and by whom the workspace was closed; a restore clears both.
    sa.Column("closed_at", sa.String(40)),
    sa.Column("closed_by", sa.String(64)),
    info=TENANT_SCOPED,
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
    # Migration 0013 (c-198): an archived team keeps what it owns and leaves its members' tokens.
    # active | archived | deleted (c-529: never removed as a row, since audit entries reference it)
    sa.Column("status", sa.String(16), nullable=False, server_default="active"),
    sa.Column("archived_at", sa.String(40)),
    # The lower-case name: two teams of one workspace never share a name in any case, on every database.
    sa.Column("name_key", sa.String(200), nullable=False, default=_name_key),
    sa.Column("template_id", sa.String(64)),  # the provisioning template's id for a team it made (c-175)
    sa.Column("protection", sa.String(16), nullable=False, server_default="none"),  # none | managed | system
    sa.UniqueConstraint("tenant_id", "id", name="uq_teams_tenant_id"),
    sa.UniqueConstraint("tenant_id", "name_key", name="uq_teams_tenant_name"),
    info=TENANT_SCOPED,
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
    info=TENANT_SCOPED,
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
    info=TENANT_SCOPED,
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
    # What the key may start (c-246): agent or workflow, its id, and a pinned workflow version (null: the live one). No
    # target: any live workflow of the key's team.
    sa.Column("target_kind", sa.String(16)),
    sa.Column("target_id", sa.String(64)),
    sa.Column("target_version", sa.Integer),
    sa.ForeignKeyConstraint(["tenant_id", "team_id"], ["teams.tenant_id", "teams.id"], name="fk_api_keys_team"),
    sa.ForeignKeyConstraint(["tenant_id", "created_by"], ["users.tenant_id", "users.id"], name="fk_api_keys_creator"),
    info=TENANT_SCOPED,
)

sessions = sa.Table(
    "sessions",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
    sa.Column("user_id", sa.String(64), nullable=False, index=True),
    sa.Column("auth_method", sa.String(16), nullable=False),  # dev | invite | password | oidc | saml
    # The sign-in provider the session started with (migration 0010); an SSO step-up goes back to it. Null: password.
    sa.Column("provider_id", sa.String(64)),
    # Rotated on every refresh; presenting an earlier one revokes the session.
    sa.Column("refresh_hash", sa.String(64), nullable=False, unique=True),
    sa.Column("expires_at", sa.String(40), nullable=False),
    sa.Column("revoked_at", sa.String(40)),
    sa.Column("last_seen_at", sa.String(40), nullable=False),
    sa.Column("created_at", sa.String(40), nullable=False),
    sa.ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_sessions_user"),
    info=TENANT_SCOPED,
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
    info=TENANT_SCOPED,
)

roles = sa.Table(
    "roles",
    metadata,
    sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("builtin", sa.Boolean, nullable=False),
    sa.Column("description", sa.String(500), nullable=False),
    sa.Column("created_at", sa.String(40), nullable=False),
    info=TENANT_SCOPED,
)

role_permissions = sa.Table(
    "role_permissions",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("role_id", sa.String(64), primary_key=True),
    sa.Column("area", sa.String(32), primary_key=True),
    sa.Column("action", sa.String(16), primary_key=True),
    sa.Column("scope", sa.String(8), nullable=False),  # all | own
    sa.ForeignKeyConstraint(["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"], name="fk_role_permissions_role"),
    info=TENANT_SCOPED,
)

role_assignments = sa.Table(
    "role_assignments",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
    sa.Column("subject_kind", sa.String(8), nullable=False),  # person | team
    sa.Column("subject_id", sa.String(64), nullable=False),  # a user id or a team id
    sa.Column("role_id", sa.String(64), nullable=False),
    sa.Column("team_id", sa.String(64), nullable=False),  # the team it applies in, or * for every team
    sa.Column("expires_at", sa.String(40)),  # null: no expiry
    sa.Column("granted_by", sa.String(320), nullable=False),
    sa.Column("reason", sa.String(500), nullable=False),
    # membership: kept equal to members.role by the member routes; grant: given on its own (c-151, c-152).
    sa.Column("source", sa.String(16), nullable=False),
    sa.Column("created_at", sa.String(40), nullable=False),
    # One assignment per subject, role and team: a repeat grant extends or replaces it, never stacks.
    sa.UniqueConstraint("tenant_id", "subject_kind", "subject_id", "role_id", "team_id", name="uq_role_assignments"),
    sa.Index("ix_role_assignments_subject", "tenant_id", "subject_id"),
    sa.ForeignKeyConstraint(["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"], name="fk_role_assignments_role"),
    info=TENANT_SCOPED,
)
# One owner per workspace (c-529): two transfers racing cannot both leave an Owner assignment behind.
sa.Index(
    "ux_role_assignments_owner",
    role_assignments.c.tenant_id,
    unique=True,
    postgresql_where=role_assignments.c.role_id == OWNER.id,
    mssql_where=role_assignments.c.role_id == OWNER.id,
    sqlite_where=role_assignments.c.role_id == OWNER.id,
)

# Sign-in (migration 0010, c-188). A workspace with no enabled provider signs in by password; once one is enabled,
# the enabled rows are its methods. A domain row sends an email domain to one SSO provider; a domain is unique
# across tenants, so one address never has two workspaces to sign in to. An identity links a provider's subject to a
# person, unique per provider, so a first sign-in that races itself links one person. A flow is one round trip to an
# identity provider: its state and its handoff code are stored hashed and used once; the PKCE verifier is kept as is
# because the code exchange needs it, and it lives ten minutes. Password credentials and reset tokens are stored as
# hashes only.
signin_providers = sa.Table(
    "signin_providers",
    metadata,
    # Ids are chosen by the workspace's admin, so they are unique per tenant: another tenant's id never collides.
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), primary_key=True),
    sa.Column("kind", sa.String(16), nullable=False),  # password | oidc | saml
    sa.Column("label", sa.String(200), nullable=False),
    sa.Column("enabled", sa.Boolean, nullable=False),
    # Non-secret settings; a client secret is named here (clientSecretRef) and read from settings, never stored.
    sa.Column("config", sa.JSON, nullable=False),
    # A person new to the workspace joins this team with this role on their first sign-in; null team: no new people.
    sa.Column("jit_team_id", sa.String(64)),
    sa.Column("jit_role", sa.String(16)),
    sa.Column("created_at", sa.String(40), nullable=False),
    sa.Column("updated_at", sa.String(40), nullable=False),
    sa.ForeignKeyConstraint(["tenant_id", "jit_team_id"], ["teams.tenant_id", "teams.id"], name="fk_signin_jit_team"),
    info=TENANT_SCOPED,
)

signin_domains = sa.Table(
    "signin_domains",
    metadata,
    sa.Column("domain", sa.String(253), primary_key=True),  # lower-case
    sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), primary_key=True, index=True),
    sa.Column("provider_id", sa.String(64), nullable=False),
    sa.Column("created_at", sa.String(40), nullable=False),
    # The value the workspace publishes as `ops-ai-verify=<token>` in the domain's TXT records.
    sa.Column("token", sa.String(64), nullable=False),
    # Set when the record was seen; only then does the domain route sign-in (c-195).
    sa.Column("verified_at", sa.String(40)),
    sa.ForeignKeyConstraint(
        ["tenant_id", "provider_id"],
        ["signin_providers.tenant_id", "signin_providers.id"],
        name="fk_signin_domains_provider",
        ondelete="CASCADE",
    ),
    info=TENANT_SCOPED,
)
# One verified owner per domain, so a domain's people go to one workspace's provider; a pending claim blocks nobody.
sa.Index(
    "ux_signin_domains_verified",
    signin_domains.c.domain,
    unique=True,
    postgresql_where=signin_domains.c.verified_at.isnot(None),
    mssql_where=signin_domains.c.verified_at.isnot(None),
    sqlite_where=signin_domains.c.verified_at.isnot(None),
)

signin_identities = sa.Table(
    "signin_identities",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
    sa.Column("provider_id", sa.String(64), nullable=False),
    sa.Column("subject", sa.String(255), nullable=False),
    sa.Column("user_id", sa.String(64), nullable=False),
    sa.Column("created_at", sa.String(40), nullable=False),
    sa.Column("last_used_at", sa.String(40), nullable=False),
    # One person per provider subject: two first sign-ins racing each other link one person.
    sa.UniqueConstraint("tenant_id", "provider_id", "subject", name="uq_signin_identities_subject"),
    sa.ForeignKeyConstraint(
        ["tenant_id", "provider_id"],
        ["signin_providers.tenant_id", "signin_providers.id"],
        name="fk_signin_identities_provider",
        ondelete="CASCADE",
    ),
    sa.ForeignKeyConstraint(
        ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_signin_identities_user"
    ),
    info=TENANT_SCOPED,
)

signin_flows = sa.Table(
    "signin_flows",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
    sa.Column("provider_id", sa.String(64), nullable=False),
    sa.Column("purpose", sa.String(16), nullable=False),  # sign_in | step_up
    sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
    # The hash of the key the starting browser holds; completing the flow needs it.
    sa.Column("browser_hash", sa.String(64), nullable=False),
    sa.Column("verifier", sa.String(128)),  # OIDC PKCE
    sa.Column("nonce", sa.String(128)),  # OIDC
    sa.Column("request_id", sa.String(64)),  # SAML AuthnRequest ID
    sa.Column("next_path", sa.String(500)),
    sa.Column("session_id", sa.String(64)),  # step-up: the session it confirms
    sa.Column("user_id", sa.String(64)),  # set when the provider answered
    sa.Column("handoff_hash", sa.String(64), unique=True),
    sa.Column("created_at", sa.String(40), nullable=False),
    sa.Column("expires_at", sa.String(40), nullable=False),
    sa.Column("answered_at", sa.String(40)),
    sa.Column("used_at", sa.String(40)),
    sa.ForeignKeyConstraint(
        ["tenant_id", "provider_id"],
        ["signin_providers.tenant_id", "signin_providers.id"],
        name="fk_signin_flows_provider",
        ondelete="CASCADE",
    ),
    info=TENANT_SCOPED,
)

password_credentials = sa.Table(
    "password_credentials",
    metadata,
    sa.Column("user_id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
    sa.Column("hash", sa.String(255), nullable=False),
    sa.Column("updated_at", sa.String(40), nullable=False),
    sa.ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_password_user"),
    info=TENANT_SCOPED,
)

password_resets = sa.Table(
    "password_resets",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
    sa.Column("user_id", sa.String(64), nullable=False),
    sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
    sa.Column("created_at", sa.String(40), nullable=False),
    sa.Column("expires_at", sa.String(40), nullable=False),
    sa.Column("used_at", sa.String(40)),
    sa.ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_password_resets_user"),
    info=TENANT_SCOPED,
)

# Wrong passwords per person in the current window, and until when sign-in and step-up refuse them (c-196).
signin_lockouts = sa.Table(
    "signin_lockouts",
    metadata,
    sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), primary_key=True),
    sa.Column("user_id", sa.String(64), primary_key=True),
    sa.Column("failures", sa.Integer, nullable=False),
    sa.Column("first_failed_at", sa.String(40), nullable=False),
    sa.Column("locked_until", sa.String(40)),
    sa.ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_signin_lockouts_user"),
    info=TENANT_SCOPED,
)

# Wrong passwords at sign-in per email address, known or not (c-196): the address as a SHA-256 of its lowercased form,
# with no tenant, since sign-in names none. An address that matches nobody locks exactly as a known one does.
signin_email_failures = sa.Table(
    "signin_email_failures",
    metadata,
    sa.Column("email_hash", sa.String(64), primary_key=True),
    sa.Column("failures", sa.Integer, nullable=False),
    sa.Column("first_failed_at", sa.String(40), nullable=False),
    sa.Column("locked_until", sa.String(40)),
)

# The stricter rules an admin has switched on (c-186): one row per policy a tenant has set, the value as JSON; a policy
# with no row has its open default from ops_access.POLICIES. A change bumps `tenants.permission_version`, since tokens
# carry the values, and is recorded in audit_entries with its before and after.
policies = sa.Table(
    "policies",
    metadata,
    sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), primary_key=True),
    sa.Column("key", sa.String(64), primary_key=True),
    sa.Column("value", sa.JSON(none_as_null=False), nullable=False),
    sa.Column("updated_by", sa.String(320), nullable=False),
    sa.Column("updated_at", sa.String(40), nullable=False),
    info=TENANT_SCOPED,
)

SIGNIN_TABLES = (
    signin_providers,
    signin_domains,
    signin_identities,
    signin_flows,
    password_credentials,
    password_resets,
)
TENANT_TABLES = (
    teams,
    users,
    members,
    api_keys,
    sessions,
    audit_entries,
    roles,
    role_permissions,
    role_assignments,
    *SIGNIN_TABLES,
    policies,
)
