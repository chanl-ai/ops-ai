"""A person who collected several subjects at one provider before `uq_signin_identities_person` keeps only their most
recently used link through the upgrade; each removed link is audited with its subject, that person's sessions end, and
other people's links and sessions stay. The upgrade runs as a login that owns the tables but is no superuser, as a
deployment's migrator is, so a write the isolation policy hides would leave the duplicates and fail the constraint.
Synchronous: Alembic's environment runs its own event loop."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.ids import new_id

from .conftest import alembic_config

BEFORE = "20261122_2022_list_sort_indexes"
# The tables the chain from BEFORE to head writes: this migration, the next (members) and the watches cells.
OWNED = (
    "signin_identities",
    "sessions",
    "audit_entries",
    "signin_flows",
    "members",
    "roles",
    "role_permissions",
    "tenants",
)
T0 = "2026-01-01T00:00:00.000Z"


async def _run(url: str, statements: list[tuple[str, dict[str, Any]]]) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as c:
        for sql, params in statements:
            await c.execute(sa.text(sql), params)
    await engine.dispose()


def _seed(tenant: str, ana: str, bo: str) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = [
        (
            "INSERT INTO tenants (id, name, status, allowed_domains, created_at) VALUES (:t, :t, 'active', '[]', :at)",
            {"t": tenant, "at": T0},
        ),
        (
            "INSERT INTO signin_providers (id, tenant_id, kind, label, enabled, config, created_at, updated_at)"
            " VALUES ('sip_m', :t, 'oidc', 'Bank', true, '{}', :at, :at)",
            {"t": tenant, "at": T0},
        ),
        # A built-in role the later cell migrations give their cells to, read back as the migrator could see it.
        (
            "INSERT INTO roles (tenant_id, id, name, builtin, description, created_at)"
            " VALUES (:t, 'builder', 'Builder', true, '', :at)",
            {"t": tenant, "at": T0},
        ),
    ]
    for user in (ana, bo):
        out.append(
            (
                "INSERT INTO users (id, tenant_id, email, name, status, created_at)"
                " VALUES (:u, :t, :u, :u, 'active', :at)",
                {"u": user, "t": tenant, "at": T0},
            )
        )
        out.append(
            (
                "INSERT INTO sessions (id, tenant_id, user_id, auth_method, refresh_hash, expires_at, last_seen_at,"
                " created_at) VALUES (:i, :t, :u, 'oidc', :h, '2099-01-01T00:00:00.000Z', :at, :at)",
                {"i": new_id("ses"), "t": tenant, "u": user, "h": new_id("rh"), "at": T0},
            )
        )
    # Ana's first link is the one she still uses; the later one was attached by email and never used since.
    for sid, user, subject, created, used in (
        ("sid_used", ana, "own-account", "2026-02-01T00:00:00.000Z", "2026-05-01T00:00:00.000Z"),
        ("sid_stale", ana, 'second-"account', "2026-03-01T00:00:00.000Z", "2026-03-01T00:00:00.000Z"),
        ("sid_bo", bo, "bo-account", "2026-03-01T00:00:00.000Z", "2026-03-01T00:00:00.000Z"),
    ):
        out.append(
            (
                "INSERT INTO signin_identities (id, tenant_id, provider_id, subject, user_id, created_at,"
                " last_used_at) VALUES (:i, :t, 'sip_m', :s, :u, :c, :l)",
                {"i": f"{sid}_{tenant[4:]}", "t": tenant, "s": subject, "u": user, "c": created, "l": used},
            )
        )
    return out


async def _cells(url: str, tenant: str) -> tuple[int, int]:
    """The tenant's watches cells and permission version after the chain ran under a role bound by the policies."""
    engine = create_async_engine(url)
    async with engine.connect() as c:
        q = "SELECT count(*) FROM role_permissions WHERE tenant_id = :t AND area = 'watches'"
        cells = (await c.execute(sa.text(q), {"t": tenant})).scalar_one()
        v = "SELECT permission_version FROM tenants WHERE id = :t"
        version = (await c.execute(sa.text(v), {"t": tenant})).scalar_one()
    await engine.dispose()
    return int(cells), int(version)


async def _state(url: str, tenant: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]], set[str]]:
    engine = create_async_engine(url)
    async with engine.connect() as c:
        links = sa.text("SELECT user_id, subject FROM signin_identities WHERE tenant_id = :t ORDER BY user_id")
        audit = sa.text("SELECT target_id, detail FROM audit_entries WHERE tenant_id = :t AND action = 'signin.unlink'")
        ended = sa.text("SELECT user_id FROM sessions WHERE tenant_id = :t AND revoked_at IS NOT NULL")
        found = [(str(r[0]), str(r[1])) for r in (await c.execute(links, {"t": tenant})).all()]
        rows = (await c.execute(audit, {"t": tenant})).all()
        unlinked = [(str(r[0]), str((r[1] if isinstance(r[1], dict) else json.loads(r[1]))["subject"])) for r in rows]
        revoked = {str(r[0]) for r in (await c.execute(ended, {"t": tenant})).all()}
    await engine.dispose()
    return found, unlinked, revoked


@pytest.mark.postgresql_only("SQL Server's scratch database holds the golden DDL, not the chain")
def test_a_person_with_two_subjects_keeps_the_one_they_use(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    tenant, ana, bo = new_id("ten"), new_id("usr"), new_id("usr")
    url = sa.engine.make_url(database_url)
    role = f"ops_migrator_{new_id('r')[2:10].lower()}"
    command.downgrade(alembic_config(), BEFORE)
    asyncio.run(_run(database_url, _seed(tenant, ana, bo)))
    owned: list[tuple[str, dict[str, Any]]] = [(f"ALTER TABLE {t} OWNER TO {role}", {}) for t in OWNED]
    asyncio.run(
        _run(
            database_url,
            [
                (f"CREATE ROLE {role} LOGIN PASSWORD 'pw' NOBYPASSRLS NOSUPERUSER", {}),
                (f"GRANT USAGE, CREATE ON SCHEMA public TO {role}", {}),
                (f"GRANT SELECT, UPDATE ON alembic_version_platform TO {role}", {}),
                (f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {role}", {}),
                *owned,
            ],
        )
    )
    try:
        monkeypatch.setenv(
            "OPS_DATABASE_URL", url.set(username=role, password="pw").render_as_string(hide_password=False)
        )
        command.upgrade(alembic_config(), "head")
        monkeypatch.undo()
        links, unlinked, revoked = asyncio.run(_state(database_url, tenant))
        assert links == sorted([(ana, "own-account"), (bo, "bo-account")])
        assert unlinked == [(ana, 'second-"account')] and revoked == {ana}
        cells, version = asyncio.run(_cells(database_url, tenant))
        assert cells >= 8 and version > 1, (cells, version)
    finally:
        monkeypatch.undo()
        back: list[tuple[str, dict[str, Any]]] = [(f"ALTER TABLE {t} OWNER TO {url.username}", {}) for t in OWNED]
        asyncio.run(
            _run(
                database_url,
                [
                    *back,
                    (f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {role}", {}),
                    (f"REVOKE ALL ON SCHEMA public FROM {role}", {}),
                    (f"DROP ROLE {role}", {}),
                ],
            )
        )
        command.upgrade(alembic_config(), "head")
