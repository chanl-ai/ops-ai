"""SAML providers get their own addresses and a list of trusted certificates

Addresses.
A provider id is chosen by a workspace's admin and is unique within that workspace only, so it cannot name a provider
in a URL that any identity provider may post to. `sp_id` is a random id set when a provider is created; the consumer
URL `/v1/auth/saml/acs/{sp_id}` and metadata `/v1/auth/saml/metadata/{sp_id}` carry it, and the unique index makes
it name one provider across workspaces. Providers saved before this revision keep a null `sp_id` and the shared
consumer URL. `platform_signin_sp` finds the provider an address names, before the tenant is known, and returns only
what the consumer route needs: tenant, provider, kind, whether it is on and whether its app-portal tile is.

Certificates. `signin_certificates` holds every signing certificate a provider is trusted with, keyed by provider and
SHA-256 fingerprint (two workspaces may trust one provider's certificate), with its dates, where it came from
(metadata, upload, manual), when it was removed, and the last expiry warning sent. Its own table, so the daily watch
finds expiring rows with one indexed query. Each provider's `config.certificate` is copied in as `manual`; the key stays
readable for one release. `platform_signin_watch` lists the SAML providers of open workspaces for that watch.

Revision ID: 0033_saml_sign_in
Revises: 0032_webhooks_usage_cells
"""

from __future__ import annotations

import hashlib
import json

import sqlalchemy as sa
from alembic import op
from cryptography import x509
from cryptography.hazmat.primitives import serialization

revision = "0033_saml_sign_in"
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

WATCH = "platform_signin_watch()"
WATCH_RETURNS = "RETURNS TABLE (tenant_id varchar, provider_id varchar)"
WATCH_BODY = (
    "SELECT p.tenant_id, p.id FROM public.signin_providers p JOIN public.tenants t ON t.id = p.tenant_id "
    "WHERE p.kind = 'saml' AND t.status = 'active'"
)
FUNCTIONS = {SIGNATURE: (RETURNS, BODY), WATCH: (WATCH_RETURNS, WATCH_BODY)}


def _iso(t: object) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")  # type: ignore[attr-defined]


def _backfill() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT tenant_id, id, config, created_at FROM signin_providers WHERE kind = 'saml'"))
    for tenant_id, provider_id, stored, created_at in rows.all():
        config = json.loads(stored) if isinstance(stored, str) else (stored or {})
        pem = config.get("certificate")
        try:
            cert = x509.load_pem_x509_certificate(str(pem).encode())
        except ValueError:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO signin_certificates (tenant_id, provider_id, fingerprint, pem, not_before, not_after, "
                "source, added_at, added_by) VALUES (:t, :p, :f, :pem, :nb, :na, 'manual', :at, 'migration')"
            ),
            {
                "t": tenant_id,
                "p": provider_id,
                "f": hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest(),
                "pem": cert.public_bytes(serialization.Encoding.PEM).decode(),
                "nb": _iso(cert.not_valid_before_utc),
                "na": _iso(cert.not_valid_after_utc),
                "at": created_at,
            },
        )


def upgrade() -> None:
    op.add_column("signin_providers", sa.Column("sp_id", sa.String(40)))
    op.create_index("ux_signin_providers_sp_id", "signin_providers", ["sp_id"], unique=True)
    op.create_table(
        "signin_certificates",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("provider_id", sa.String(64), primary_key=True),
        sa.Column("fingerprint", sa.String(64), primary_key=True),
        sa.Column("pem", sa.Text, nullable=False),
        sa.Column("not_before", sa.String(40), nullable=False),
        sa.Column("not_after", sa.String(40), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("added_at", sa.String(40), nullable=False),
        sa.Column("added_by", sa.String(64), nullable=False),
        sa.Column("removed_at", sa.String(40)),
        sa.Column("warned", sa.String(16)),
        sa.ForeignKeyConstraint(
            ["tenant_id", "provider_id"],
            ["signin_providers.tenant_id", "signin_providers.id"],
            name="fk_signin_certificates_provider",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_signin_certificates_not_after", "signin_certificates", ["not_after"])
    _backfill()
    if op.get_bind().dialect.name != "postgresql":
        return
    table = "signin_certificates"
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {TENANT}")
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant ON {table} "
        "USING (tenant_id = current_setting('app.tenant_id', true)) "
        "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
    )
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
    op.drop_table("signin_certificates")
    op.drop_index("ux_signin_providers_sp_id", table_name="signin_providers")
    op.drop_column("signin_providers", "sp_id")
