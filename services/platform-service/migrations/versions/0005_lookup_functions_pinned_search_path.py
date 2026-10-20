"""the pre-tenant lookup functions read only public's tables, whatever a session puts in its temporary schema

Postgres searches a session's temporary schema before a function's search_path unless pg_temp is named in it, so
the lookups of migration 0004 (search_path = public, unqualified tables) would read a session's temp `users` table
in place of the real one. Each function is recreated with search_path = pg_catalog, public, pg_temp and every table
qualified with public. CREATE OR REPLACE keeps each function's owner and grants.

Revision ID: 0005_lookup_paths
Revises: 0004_lookups
"""

from __future__ import annotations

from alembic import op

revision = "0005_lookup_paths"
down_revision = "0004_lookups"
branch_labels = None
depends_on = None

PINNED = "SET search_path = pg_catalog, public, pg_temp"
LOOSE = "SET search_path = public"

FUNCTIONS = {
    "platform_users_by_email(p_email text)": (
        "RETURNS TABLE (tenant_id varchar, id varchar, email varchar, name varchar)",
        "SELECT u.tenant_id, u.id, u.email, u.name FROM {s}users u "
        "WHERE lower(u.email) = lower(p_email) AND u.status = 'active'",
    ),
    "platform_session(p_id text)": (
        "RETURNS TABLE (tenant_id varchar, user_id varchar, id varchar)",
        "SELECT s.tenant_id, s.user_id, s.id FROM {s}sessions s WHERE s.id = p_id",
    ),
    "platform_key(p_prefix text, p_now text)": (
        "RETURNS TABLE (id varchar, tenant_id varchar, team_id varchar, secret_hash varchar, scopes json, "
        "created_by varchar, usable boolean)",
        "SELECT k.id, k.tenant_id, k.team_id, k.secret_hash, k.scopes, k.created_by, "
        "k.revoked_at IS NULL AND k.disabled_at IS NULL AND (k.expires_at IS NULL OR k.expires_at > p_now) "
        "FROM {s}api_keys k WHERE k.prefix = p_prefix",
    ),
    "platform_invite(p_hash text)": (
        "RETURNS TABLE (member_id varchar, tenant_id varchar, team_id varchar, team varchar, email varchar, "
        "role varchar, status varchar, invited_at varchar, expires_at varchar, allowed_domains json)",
        "SELECT m.id, m.tenant_id, m.team_id, t.name, m.email, m.role, m.status, m.created_at, "
        "m.invite_expires_at, n.allowed_domains "
        "FROM {s}members m JOIN {s}teams t ON t.id = m.team_id JOIN {s}tenants n ON n.id = m.tenant_id "
        "WHERE m.invite_token_hash = p_hash",
    ),
}


def _replace(schema: str, path: str) -> None:
    for signature, (returns, body) in FUNCTIONS.items():
        op.execute(
            f"CREATE OR REPLACE FUNCTION {signature} {returns} AS $$ {body.format(s=schema)} $$ "
            f"LANGUAGE sql STABLE SECURITY DEFINER {path}"
        )


def upgrade() -> None:
    _replace("public.", PINNED)


def downgrade() -> None:
    _replace("", LOOSE)
