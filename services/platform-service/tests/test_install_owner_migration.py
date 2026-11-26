"""Migration 20261125_1300 by failure mode: a workspace made before `install.manage` keeps its Owner role's stored
rows, which decide over the seed, so without the backfill its owner could never change the install's model aliases;
and the cell reaching any role but Owner. Runs the real chain on the test database."""

from __future__ import annotations

import asyncio
from typing import Any

import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.ids import new_id, now_iso

from .conftest import alembic_config

BEFORE = "20261124_0100_close_invites"


async def _run(url: str, statements: list[tuple[str, dict[str, Any]]]) -> list[list[Any]]:
    engine = create_async_engine(url)
    out: list[list[Any]] = []
    async with engine.begin() as c:
        for sql, params in statements:
            result = await c.execute(sa.text(sql), params)
            out.append(list(result.all()) if result.returns_rows else [])
    await engine.dispose()
    return out


def test_an_existing_owner_gains_install_manage_and_no_other_role_does(database_url: str) -> None:
    tenant, now = new_id("ten"), now_iso()
    command.downgrade(alembic_config(), BEFORE)
    try:
        writes: list[tuple[str, dict[str, Any]]] = [
            (
                "INSERT INTO tenants (id, name, status, allowed_domains, created_at) "
                "VALUES (:t, :t, 'active', '[]', :now)",
                {"t": tenant, "now": now},
            )
        ]
        for role, cell in (("owner", ("workspace", "manage")), ("admin", ("agents", "manage"))):
            writes += [
                (
                    "INSERT INTO roles (tenant_id, id, name, builtin, description, created_at) "
                    "VALUES (:t, :id, :id, true, '', :now)",
                    {"t": tenant, "id": role, "now": now},
                ),
                (
                    "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
                    "VALUES (:t, :r, :a, :x, 'all')",
                    {"t": tenant, "r": role, "a": cell[0], "x": cell[1]},
                ),
            ]
        writes.append(("SELECT permission_version FROM tenants WHERE id = :t", {"t": tenant}))
        version_before = asyncio.run(_run(database_url, writes))[-1][0][0]
    finally:
        command.upgrade(alembic_config(), "head")

    held, version = asyncio.run(
        _run(
            database_url,
            [
                (
                    "SELECT role_id FROM role_permissions WHERE tenant_id = :t AND area = 'install' "
                    "AND action = 'manage'",
                    {"t": tenant},
                ),
                ("SELECT permission_version FROM tenants WHERE id = :t", {"t": tenant}),
            ],
        )
    )
    assert [r[0] for r in held] == ["owner"]
    # A token minted before the upgrade carries the old version and is renewed, so the owner's next request holds it.
    assert version[0][0] > version_before
