"""sign-in domains are claimed per workspace and route sign-in only once verified by DNS

A domain listed on a provider was owned by the first workspace to list it (the key was the domain alone) and routed
sign-in at once. Now a listing is a claim of one workspace, keyed (domain, tenant_id), carrying a random token the
workspace publishes as a TXT record; `verified_at` is set when the record is seen (c-195). The partial unique index on
verified domains is what stops two workspaces sending the same domain's people to different providers, and a pending
claim blocks nobody. `platform_signin_domain` returns verified claims only. Claims that exist before this revision are
marked verified: they were set by Security admins in development data, and unverifying them would stop sign-in there.

Revision ID: 0017_signin_domain_verification
Revises: 0016_admin_every_cell
"""

from __future__ import annotations

import secrets

import sqlalchemy as sa
from alembic import op

revision = "0017_signin_domain_verification"
down_revision = "0016_admin_every_cell"
branch_labels = None
depends_on = None

PINNED = "SET search_path = pg_catalog, public, pg_temp"
SIGNATURE = "platform_signin_domain(p_domain text)"
RETURNS = (
    "RETURNS TABLE (tenant_id varchar, provider_id varchar, kind varchar, label varchar, enabled boolean, "
    "password_enabled boolean)"
)


def _body(verified_only: bool) -> str:
    return (
        "SELECT d.tenant_id, d.provider_id, p.kind, p.label, p.enabled, "
        "EXISTS (SELECT 1 FROM public.signin_providers q WHERE q.tenant_id = d.tenant_id AND q.kind = 'password' "
        "AND q.enabled) "
        "FROM public.signin_domains d JOIN public.signin_providers p ON p.id = d.provider_id "
        "AND p.tenant_id = d.tenant_id WHERE d.domain = lower(p_domain)"
        + (" AND d.verified_at IS NOT NULL" if verified_only else "")
    )


def _replace_lookup(verified_only: bool) -> None:
    if op.get_bind().dialect.name == "postgresql":
        # Same signature and return type, so the owner and grants of 0010 stay.
        op.execute(
            f"CREATE OR REPLACE FUNCTION {SIGNATURE} {RETURNS} AS $$ {_body(verified_only)} $$ "
            f"LANGUAGE sql STABLE SECURITY DEFINER {PINNED}"
        )


def upgrade() -> None:
    op.add_column("signin_domains", sa.Column("token", sa.String(64)))
    op.add_column("signin_domains", sa.Column("verified_at", sa.String(40)))
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT domain, created_at FROM signin_domains")).all()
    for domain, created_at in rows:
        bind.execute(
            sa.text("UPDATE signin_domains SET token = :t, verified_at = :v WHERE domain = :d"),
            {"t": secrets.token_urlsafe(24), "v": created_at, "d": domain},
        )
    with op.batch_alter_table("signin_domains") as b:
        b.alter_column("token", existing_type=sa.String(64), nullable=False)
        b.drop_constraint("signin_domains_pkey", type_="primary")
        b.create_primary_key("signin_domains_pkey", ["domain", "tenant_id"])
    # One verified owner per domain: the guarantee that a domain's people go to one workspace's provider.
    op.create_index(
        "ux_signin_domains_verified",
        "signin_domains",
        ["domain"],
        unique=True,
        postgresql_where=sa.text("verified_at IS NOT NULL"),
        sqlite_where=sa.text("verified_at IS NOT NULL"),
    )
    _replace_lookup(verified_only=True)


def downgrade() -> None:
    _replace_lookup(verified_only=False)
    op.drop_index("ux_signin_domains_verified", table_name="signin_domains")
    op.execute("DELETE FROM signin_domains WHERE verified_at IS NULL")
    with op.batch_alter_table("signin_domains") as b:
        b.drop_constraint("signin_domains_pkey", type_="primary")
        b.create_primary_key("signin_domains_pkey", ["domain"])
    op.drop_column("signin_domains", "verified_at")
    op.drop_column("signin_domains", "token")
