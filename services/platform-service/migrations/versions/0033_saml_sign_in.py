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

Groups. `signin_group_rules` replaces `config.groups.map`: each rule is copied in, the map leaves the config, and
`source` stays there. `signin_grants` records where a membership came from, so a sign-in can remove only what a group
gave. It is filled from the audit log: each `member.jit` entry whose membership is still active becomes a `jit` grant;
each `member.group` entry becomes a `group` grant naming the provider's one rule into that membership's team with that
role, or naming no rule when no single rule explains it; it still counts as given by groups. A membership with no
entry at all counts as given by hand and is never removed by a sign-in.

Test sign-in. `signin_flows.test_result` holds what a test round trip got back, for the admin who started it.

Break-glass. `signin_break_glass` names the Security admins who may sign in by password while the workspace's
`companySignInRequired` policy is on, with when each last did.

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
TABLES = ("signin_certificates", "signin_group_rules", "signin_grants", "signin_break_glass")
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


def _json(stored: object) -> dict[str, object]:
    return json.loads(stored) if isinstance(stored, str) else dict(stored or {})  # type: ignore[call-overload]


def _backfill_groups() -> None:
    bind = op.get_bind()
    providers = bind.execute(sa.text("SELECT tenant_id, id, config, created_at FROM signin_providers")).all()
    rules: dict[tuple[str, str, str], list[str]] = {}
    for tenant_id, provider_id, stored, created_at in providers:
        config = _json(stored)
        groups = _json(config.get("groups"))
        mapped = groups.pop("map", None) or []
        for n, rule in enumerate(mapped):  # type: ignore[arg-type]
            team = str(rule["team"])  # type: ignore[index]
            if (
                bind.execute(
                    sa.text("SELECT 1 FROM teams WHERE id = :t AND tenant_id = :n"), {"t": team, "n": tenant_id}
                ).first()
                is None
            ):
                continue
            rule_id = f"sgr_{provider_id[-20:]}_{n}"
            bind.execute(
                sa.text(
                    "INSERT INTO signin_group_rules (id, tenant_id, provider_id, group_value, team_id, role, "
                    "created_at, created_by) VALUES (:i, :t, :p, :g, :team, :r, :at, 'migration')"
                ),
                {"i": rule_id, "t": tenant_id, "p": provider_id, "g": str(rule["group"]), "team": team,  # type: ignore[index]
                 "r": str(rule["role"]), "at": created_at},  # type: ignore[index]
            )  # fmt: skip
            rules.setdefault((provider_id, team, str(rule["role"])), []).append(rule_id)  # type: ignore[index]
        if mapped:
            config["groups"] = groups
            bind.execute(
                sa.text("UPDATE signin_providers SET config = :c WHERE tenant_id = :t AND id = :p"),
                {"c": json.dumps(config), "t": tenant_id, "p": provider_id},
            )
    known = {str(p[1]) for p in providers}
    entries = bind.execute(
        sa.text(
            "SELECT a.tenant_id, a.target_id, a.action, a.detail, a.at, m.team_id, m.role FROM audit_entries a "
            "JOIN members m ON m.id = a.target_id WHERE a.action IN ('member.jit', 'member.group') "
            "AND m.status = 'active' ORDER BY a.at"
        )
    ).all()
    for n, (tenant_id, member_id, action, detail, at, team, role) in enumerate(entries):
        provider = str(_json(detail).get("provider") or "")
        if provider not in known:
            continue
        found = rules.get((provider, str(team), str(role)), [])
        bind.execute(
            sa.text(
                "INSERT INTO signin_grants (id, tenant_id, member_id, provider_id, rule_id, why, granted_at) "
                "VALUES (:i, :t, :m, :p, :r, :w, :at)"
            ),
            {"i": f"sgt_mig_{n}", "t": tenant_id, "m": member_id, "p": provider,
             "r": found[0] if action == "member.group" and len(found) == 1 else None,
             "w": "jit" if action == "member.jit" else "group", "at": at},
        )  # fmt: skip


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
    op.create_table(
        "signin_group_rules",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("group_value", sa.String(255), nullable=False),
        sa.Column("team_id", sa.String(64), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.UniqueConstraint("provider_id", "group_value", "team_id", name="uq_signin_group_rules"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "provider_id"],
            ["signin_providers.tenant_id", "signin_providers.id"],
            name="fk_signin_group_rules_provider",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "team_id"], ["teams.tenant_id", "teams.id"], name="fk_signin_group_rules_team"
        ),
    )
    op.create_table(
        "signin_grants",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
        sa.Column(
            "member_id", sa.String(64), sa.ForeignKey("members.id", ondelete="CASCADE"), nullable=False, index=True
        ),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("rule_id", sa.String(64), sa.ForeignKey("signin_group_rules.id", ondelete="SET NULL")),
        sa.Column("why", sa.String(8), nullable=False),
        sa.Column("granted_at", sa.String(40), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id", "provider_id"],
            ["signin_providers.tenant_id", "signin_providers.id"],
            name="fk_signin_grants_provider",
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "signin_break_glass",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("added_by", sa.String(64), nullable=False),
        sa.Column("added_at", sa.String(40), nullable=False),
        sa.Column("last_used_at", sa.String(40)),
        sa.ForeignKeyConstraint(
            ["tenant_id", "user_id"],
            ["users.tenant_id", "users.id"],
            name="fk_signin_break_glass_user",
            ondelete="CASCADE",
        ),
    )
    op.add_column("signin_flows", sa.Column("test_result", sa.JSON(none_as_null=True)))
    _backfill()
    _backfill_groups()
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
    op.drop_column("signin_flows", "test_result")
    op.drop_table("signin_break_glass")
    op.drop_table("signin_grants")
    op.drop_table("signin_group_rules")
    op.drop_table("signin_certificates")
    op.drop_index("ux_signin_providers_sp_id", table_name="signin_providers")
    op.drop_column("signin_providers", "sp_id")
