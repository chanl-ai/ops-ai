"""Migration 0006 keeps every member's access (c-147), by failure mode: an active member left without the built-in role
their membership names, a Security team admin left without Security admin, an invited or removed member given a role,
and the migration's frozen copy of the grid drifting from `ops_access` (the catalogue). Runs the real chain on the
test database: down to 0005, members of every role written as the superuser, up to head. Synchronous: Alembic's
environment runs its own event loop."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from ops_access import BUILTIN_ROLES, Assignment, builtin_roles_for, effective
from ops_service_kit.ids import new_id, now_iso

from .conftest import alembic_config

GRIDS = {r.id: r.grants for r in BUILTIN_ROLES}
NAMES = {r.id: r.name for r in BUILTIN_ROLES}
NOW = "2026-10-17T00:00:00.000Z"


async def _run(url: str, statements: list[tuple[str, dict[str, Any]]]) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as c:
        for sql, params in statements:
            await c.execute(sa.text(sql), params)
    await engine.dispose()


async def _rows(url: str, sql: str, params: dict[str, Any]) -> list[Any]:
    engine = create_async_engine(url)
    async with engine.connect() as c:
        rows = (await c.execute(sa.text(sql), params)).all()
    await engine.dispose()
    return list(rows)


def test_every_member_keeps_their_access(database_url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    tenant, ops, security = new_id("ten"), new_id("team"), new_id("team")
    monkeypatch.setenv("OPS_SECURITY_TEAM_ID", security)
    now = now_iso()
    people = {role: new_id("usr") for role in ("admin", "builder", "approver", "viewer")}
    command.downgrade(alembic_config(), "0005_lookup_paths")
    try:
        writes: list[tuple[str, dict[str, Any]]] = [
            (
                "INSERT INTO tenants (id, name, status, allowed_domains, created_at) "
                "VALUES (:t, :t, 'active', '[]', :now)",
                {"t": tenant, "now": now},
            )
        ]
        for team in (ops, security):
            writes.append(
                (
                    "INSERT INTO teams (id, tenant_id, name, owner_groups, scope, created_at) "
                    "VALUES (:id, :t, :id, '[]', 'owned', :now)",
                    {"id": team, "t": tenant, "now": now},
                )
            )
        for role, user in people.items():
            writes.append(
                (
                    "INSERT INTO users (id, tenant_id, email, name, status, created_at) "
                    "VALUES (:u, :t, :e, 'P', 'active', :now)",
                    {"u": user, "t": tenant, "e": f"{user}@bank.test", "now": now},
                )
            )
            for team in (ops, security):
                writes.append(_member(tenant, team, user, role, "active", now=now))
        # Neither an invitation nor a removed membership grants anything.
        writes.append(_member(tenant, ops, None, "admin", "invited", now=now))
        removed = new_id("usr")
        writes.append(
            (
                "INSERT INTO users (id, tenant_id, email, name, status, created_at) "
                "VALUES (:u, :t, :e, 'R', 'active', :now)",
                {"u": removed, "t": tenant, "e": f"{removed}@bank.test", "now": now},
            )
        )
        writes.append(_member(tenant, ops, removed, "admin", "removed", now=now))
        asyncio.run(_run(database_url, writes))
    finally:
        command.upgrade(alembic_config(), "head")

    grid = asyncio.run(
        _rows(
            database_url,
            "SELECT role_id, area, action, scope FROM role_permissions WHERE tenant_id = :t",
            {"t": tenant},
        )
    )
    assert {r[0] for r in grid} == {r.id for r in BUILTIN_ROLES}
    for role in BUILTIN_ROLES:
        assert {(r[1], r[2], r[3]) for r in grid if r[0] == role.id} == set(role.grants), role.id

    held = asyncio.run(
        _rows(
            database_url,
            "SELECT subject_id, team_id, role_id FROM role_assignments WHERE tenant_id = :t",
            {"t": tenant},
        )
    )
    assert removed not in {r[0] for r in held}
    for role, user in people.items():
        for team in (ops, security):
            stored = [Assignment(r[2], NAMES[r[2]], r[1], "person") for r in held if r[0] == user and r[1] == team]
            expected = [
                Assignment(b, NAMES[b], team, "person") for b in builtin_roles_for(role, security_team=team == security)
            ]
            got = _flat(effective(stored, GRIDS, [team], NOW)[team])
            want = _flat(effective(expected, GRIDS, [team], NOW)[team])
            assert got == want and got, (role, team)
    security_admins = {r[0] for r in held if r[2] == "security_admin"}
    assert security_admins == {people["admin"]}


def _member(
    tenant: str, team: str, user: str | None, role: str, status: str, *, now: str
) -> tuple[str, dict[str, Any]]:
    return (
        "INSERT INTO members (id, tenant_id, team_id, user_id, email, role, status, created_at, updated_at) "
        "VALUES (:id, :t, :team, :u, :e, :r, :s, :now, :now)",
        {
            "id": new_id("mem"),
            "t": tenant,
            "team": team,
            "u": user,
            "e": f"{user or new_id('inv')}@bank.test",
            "r": role,
            "s": status,
            "now": now,
        },
    )


def _flat(granted: dict[tuple[str, str], Any]) -> set[tuple[str, str, str]]:
    return {(a, x, g.scope) for (a, x), g in granted.items()}


def test_the_seed_refuses_a_role_that_cannot_bypass_row_security(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run as a role without BYPASSRLS, 0006 would see no tenant and seed no role; it must stop instead."""
    role = f"ops_no_bypass_{new_id('r')[2:10].lower()}"
    url = sa.engine.make_url(database_url)
    asyncio.run(
        _run(
            database_url,
            [
                (f"CREATE ROLE {role} LOGIN PASSWORD 'pw' NOBYPASSRLS NOSUPERUSER", {}),
                (f"GRANT USAGE, CREATE ON SCHEMA public TO {role}", {}),
                (f"GRANT SELECT, UPDATE ON alembic_version_platform TO {role}", {}),
            ],
        )
    )
    command.downgrade(alembic_config(), "0005_lookup_paths")
    try:
        monkeypatch.setenv(
            "OPS_DATABASE_URL", url.set(username=role, password="pw").render_as_string(hide_password=False)
        )
        with pytest.raises(RuntimeError, match="BYPASSRLS"):
            command.upgrade(alembic_config(), "0006_roles")
    finally:
        monkeypatch.undo()
        command.upgrade(alembic_config(), "head")
        asyncio.run(
            _run(
                database_url,
                [
                    (f"REVOKE ALL ON SCHEMA public FROM {role}", {}),
                    (f"REVOKE ALL ON alembic_version_platform FROM {role}", {}),
                    (f"DROP ROLE {role}", {}),
                ],
            )
        )
