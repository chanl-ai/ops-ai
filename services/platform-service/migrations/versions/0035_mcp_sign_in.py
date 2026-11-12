"""assistants sign in to a team's MCP address: registered clients, MCP grants on sessions, a team lookup

A client registers itself before anyone signs in, so `oauth_clients` holds no tenant and no row-level security
(as `signin_email_failures`); a person's first Allow gives it a tenant. A grant is a `sessions` row of kind `mcp`
holding the client, the one team and the address, and the authorization code it was opened with. Authorizing checks
that the address names a team before anyone is signed in, so `platform_team` finds a team's tenant, as the lookups of
0004 do.

Revision ID: 0035_mcp_sign_in
Revises: 0034_saml_sign_in
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0035_mcp_sign_in"
down_revision = "0034_saml_sign_in"
branch_labels = None
depends_on = None

TENANT = "ops_platform_tenant"
LOOKUP = "ops_platform_lookup"
FUNCTION = "platform_team(p_id text)"
COLUMNS = (
    sa.Column("kind", sa.String(8), nullable=False, server_default="console"),
    sa.Column("client_id", sa.String(64)),
    sa.Column("team_id", sa.String(64)),
    sa.Column("resource", sa.String(500)),
    sa.Column("code_hash", sa.String(64)),
    sa.Column("code_challenge", sa.String(64)),
    sa.Column("redirect_uri", sa.String(500)),
    sa.Column("code_expires_at", sa.String(40)),
    sa.Column("code_used_at", sa.String(40)),
)


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("redirect_uris", sa.JSON, nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("consented_at", sa.String(40)),
        sa.Column("tenant_id", sa.String(64)),
    )
    for column in COLUMNS:
        op.add_column("sessions", column)
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON oauth_clients TO {TENANT}")
    op.execute(
        f"CREATE FUNCTION {FUNCTION} RETURNS TABLE (tenant_id varchar, id varchar, status varchar) "
        "AS $$ SELECT t.tenant_id, t.id, t.status FROM teams t WHERE t.id = p_id $$ "
        "LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public"
    )
    op.execute(f"ALTER FUNCTION {FUNCTION} OWNER TO {LOOKUP}")
    op.execute(f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO {TENANT}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP FUNCTION {FUNCTION}")
    for column in reversed(COLUMNS):
        op.drop_column("sessions", column.name)
    op.drop_table("oauth_clients")
