"""each SAML provider gets its own consumer and metadata address, found before the tenant is known

A provider id is chosen by a workspace's admin and is unique within that workspace only, so it cannot name a provider
in a URL that any identity provider may post to. `sp_id` is a random id set when a provider is created; the consumer
URL `/v1/auth/saml/acs/{sp_id}` and metadata `/v1/auth/saml/metadata/{sp_id}` carry it, and the unique index makes
it name one provider across workspaces. Providers saved before this revision keep a null `sp_id` and the shared
consumer URL. `platform_signin_sp` finds the provider an address names, before the tenant is known, and returns only
what the consumer route needs: tenant, provider, kind, whether it is on and whether its app-portal tile is.

Revision ID: 0033_saml_sp_addresses
Revises: 0032_webhooks_usage_cells
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0033_saml_sp_addresses"
down_revision = "0032_webhooks_usage_cells"
branch_labels = None
depends_on = None

TENANT = "ops_platform_tenant"
LOOKUP = "ops_platform_lookup"
PINNED = "SET search_path = pg_catalog, public, pg_temp"
SIGNATURE = "platform_signin_sp(p_sp_id text)"
RETURNS = "RETURNS TABLE (tenant_id varchar, provider_id varchar, kind varchar, enabled boolean, tiles boolean)"
BODY = (
    "SELECT p.tenant_id, p.id, p.kind, p.enabled, COALESCE((p.config->>'tiles')::boolean, true) "
    "FROM public.signin_providers p WHERE p.sp_id = p_sp_id"
)


def upgrade() -> None:
    op.add_column("signin_providers", sa.Column("sp_id", sa.String(40)))
    op.create_index("ux_signin_providers_sp_id", "signin_providers", ["sp_id"], unique=True)
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"CREATE FUNCTION {SIGNATURE} {RETURNS} AS $$ {BODY} $$ LANGUAGE sql STABLE SECURITY DEFINER {PINNED}")
    op.execute(f"ALTER FUNCTION {SIGNATURE} OWNER TO {LOOKUP}")
    op.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO {TENANT}")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP FUNCTION {SIGNATURE}")
    op.drop_index("ux_signin_providers_sp_id", table_name="signin_providers")
    op.drop_column("signin_providers", "sp_id")
