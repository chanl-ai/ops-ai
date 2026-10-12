"""the four lookups that find a tenant, as functions a role that owns nothing may call

Sign-in by email, a session by id, a key by prefix and an invite by token hash run before the tenant is known, so
row-level security as the tenant role shows them nothing. Each is a SECURITY DEFINER function owned by
`ops_platform_lookup`, a NOLOGIN role whose only right is SELECT on these tables through a SELECT-only policy. The
tenant role may execute the functions and nothing else of it, so the lookups return the few columns they need and
never a row set a caller chose.

Revision ID: 0004_lookups
Revises: 0003_key_expiry
"""

from __future__ import annotations

from alembic import op

revision = "0004_lookups"
down_revision = "0003_key_expiry"
branch_labels = None
depends_on = None

TENANT = "ops_platform_tenant"
LOOKUP = "ops_platform_lookup"
TABLES = ("tenants", "teams", "users", "members", "api_keys", "sessions")

FUNCTIONS = {
    "platform_users_by_email(p_email text)": """
        RETURNS TABLE (tenant_id varchar, id varchar, email varchar, name varchar)
        AS $$ SELECT u.tenant_id, u.id, u.email, u.name FROM users u
              WHERE lower(u.email) = lower(p_email) AND u.status = 'active' $$""",
    "platform_session(p_id text)": """
        RETURNS TABLE (tenant_id varchar, user_id varchar, id varchar)
        AS $$ SELECT s.tenant_id, s.user_id, s.id FROM sessions s WHERE s.id = p_id $$""",
    "platform_key(p_prefix text, p_now text)": """
        RETURNS TABLE (id varchar, tenant_id varchar, team_id varchar, secret_hash varchar, scopes json,
                       created_by varchar, usable boolean)
        AS $$ SELECT k.id, k.tenant_id, k.team_id, k.secret_hash, k.scopes, k.created_by,
                     k.revoked_at IS NULL AND k.disabled_at IS NULL AND (k.expires_at IS NULL OR k.expires_at > p_now)
              FROM api_keys k WHERE k.prefix = p_prefix $$""",
    "platform_invite(p_hash text)": """
        RETURNS TABLE (member_id varchar, tenant_id varchar, team_id varchar, team varchar, email varchar,
                       role varchar, status varchar, invited_at varchar, expires_at varchar, allowed_domains json)
        AS $$ SELECT m.id, m.tenant_id, m.team_id, t.name, m.email, m.role, m.status, m.created_at,
                     m.invite_expires_at, n.allowed_domains
              FROM members m JOIN teams t ON t.id = m.team_id JOIN tenants n ON n.id = m.tenant_id
              WHERE m.invite_token_hash = p_hash $$""",
}


def upgrade() -> None:
    op.execute(f"DO $$ BEGIN CREATE ROLE {LOOKUP} NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$")
    for table in TABLES:
        op.execute(f"GRANT SELECT ON {table} TO {LOOKUP}")
        op.execute(f"CREATE POLICY {table}_lookup ON {table} FOR SELECT TO {LOOKUP} USING (true)")
    for signature, body in FUNCTIONS.items():
        op.execute(f"CREATE FUNCTION {signature} {body} LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public")
        op.execute(f"ALTER FUNCTION {signature} OWNER TO {LOOKUP}")
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {TENANT}")


def downgrade() -> None:
    for signature in FUNCTIONS:
        op.execute(f"DROP FUNCTION {signature}")
    for table in TABLES:
        op.execute(f"DROP POLICY {table}_lookup ON {table}")
        op.execute(f"REVOKE SELECT ON {table} FROM {LOOKUP}")
