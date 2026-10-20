"""sign-in providers per workspace, SSO domains, provider identities, sign-in flows, password credentials and resets

A workspace with no provider rows keeps signing in by password; once it has rows they are its methods (c-188). Each
new table carries tenant_id under the same row-level security as 0001. Four lookups run before the tenant is known (an
email domain, a flow by its state or handoff hash, a reset by its token hash) and are SECURITY DEFINER functions owned
by the lookup role, as in 0004 and 0005, returning only the ids the caller needs. `sessions.provider_id` names the
provider a session started with, so an SSO step-up goes back to it.

Revision ID: 0010_sign_in
Revises: 0009_knowledge_team_shared
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_sign_in"
down_revision = "0009_knowledge_team_shared"
branch_labels = None
depends_on = None

TENANT = "ops_platform_tenant"
LOOKUP = "ops_platform_lookup"
TABLES = (
    "signin_providers",
    "signin_domains",
    "signin_identities",
    "signin_flows",
    "password_credentials",
    "password_resets",
)
LOOKUP_TABLES = ("signin_providers", "signin_domains", "signin_flows", "password_resets")
PINNED = "SET search_path = pg_catalog, public, pg_temp"

FUNCTIONS = {
    # The workspace an email domain signs in to, the SSO provider it names, and whether that workspace allows a
    # password. A domain with no row returns nothing.
    "platform_signin_domain(p_domain text)": (
        "RETURNS TABLE (tenant_id varchar, provider_id varchar, kind varchar, label varchar, enabled boolean, "
        "password_enabled boolean)",
        "SELECT d.tenant_id, d.provider_id, p.kind, p.label, p.enabled, "
        "EXISTS (SELECT 1 FROM public.signin_providers q WHERE q.tenant_id = d.tenant_id AND q.kind = 'password' "
        "AND q.enabled) "
        "FROM public.signin_domains d JOIN public.signin_providers p ON p.id = d.provider_id "
        "AND p.tenant_id = d.tenant_id WHERE d.domain = lower(p_domain)",
    ),
    "platform_signin_flow(p_state_hash text)": (
        "RETURNS TABLE (id varchar, tenant_id varchar)",
        "SELECT f.id, f.tenant_id FROM public.signin_flows f WHERE f.state_hash = p_state_hash",
    ),
    "platform_signin_handoff(p_handoff_hash text)": (
        "RETURNS TABLE (id varchar, tenant_id varchar)",
        "SELECT f.id, f.tenant_id FROM public.signin_flows f WHERE f.handoff_hash = p_handoff_hash",
    ),
    "platform_password_reset(p_hash text)": (
        "RETURNS TABLE (id varchar, tenant_id varchar)",
        "SELECT r.id, r.tenant_id FROM public.password_resets r WHERE r.token_hash = p_hash",
    ),
}


def upgrade() -> None:
    op.add_column("sessions", sa.Column("provider_id", sa.String(64)))
    op.create_table(
        "signin_providers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("config", sa.JSON, nullable=False),
        sa.Column("jit_team_id", sa.String(64)),
        sa.Column("jit_role", sa.String(16)),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "jit_team_id"], ["teams.tenant_id", "teams.id"], name="fk_signin_jit_team"
        ),
    )
    op.create_table(
        "signin_domains",
        sa.Column("domain", sa.String(253), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "provider_id"],
            ["signin_providers.tenant_id", "signin_providers.id"],
            name="fk_signin_domains_provider",
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "signin_identities",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("last_used_at", sa.String(40), nullable=False),
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
    )
    op.create_table(
        "signin_flows",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("browser_hash", sa.String(64), nullable=False),
        sa.Column("verifier", sa.String(128)),
        sa.Column("nonce", sa.String(128)),
        sa.Column("request_id", sa.String(64)),
        sa.Column("next_path", sa.String(500)),
        sa.Column("session_id", sa.String(64)),
        sa.Column("user_id", sa.String(64)),
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
    )
    op.create_table(
        "password_credentials",
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("hash", sa.String(255), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_password_user"),
    )
    op.create_table(
        "password_resets",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.String(40), nullable=False),
        sa.Column("used_at", sa.String(40)),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"], ["users.tenant_id", "users.id"], name="fk_password_resets_user"
        ),
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {TENANT}")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant ON {table} "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )
    for table in LOOKUP_TABLES:
        op.execute(f"GRANT SELECT ON {table} TO {LOOKUP}")
        op.execute(f"CREATE POLICY {table}_lookup ON {table} FOR SELECT TO {LOOKUP} USING (true)")
    for signature, (returns, body) in FUNCTIONS.items():
        op.execute(
            f"CREATE FUNCTION {signature} {returns} AS $$ {body} $$ LANGUAGE sql STABLE SECURITY DEFINER {PINNED}"
        )
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {LOOKUP}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {TENANT}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for signature in FUNCTIONS:
            op.execute(f"DROP FUNCTION {signature}")
    for table in ("password_resets", "password_credentials", "signin_flows", "signin_identities", "signin_domains"):
        op.drop_table(table)
    op.drop_table("signin_providers")
    op.drop_column("sessions", "provider_id")
