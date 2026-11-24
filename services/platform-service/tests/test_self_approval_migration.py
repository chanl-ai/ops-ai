"""The revision that clears the unused Approvals · decide cell, by failure mode: a role that stored the cell while no
code read it (a custom role copied from Admin, an edited Builder) gains self-approval once the cell is read; Admin
loses it; a cleared role leaves no audit row for the admin to read; a second run writes again. Runs the real chain on
the test database: down one revision, a workspace as it stood, up to head."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.ids import new_id, now_iso

from .conftest import alembic_config

REVISION = "20261123_1200_self_approval_cell"
BEFORE = "20261122_2022_list_sort_indexes"


async def _run(url: str, statements: list[tuple[str, dict[str, Any]]]) -> list[list[Any]]:
    engine = create_async_engine(url)
    out: list[list[Any]] = []
    async with engine.begin() as c:
        for sql, params in statements:
            result = await c.execute(sa.text(sql), params)
            out.append(list(result.all()) if result.returns_rows else [])
    await engine.dispose()
    return out


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / f"migrations/versions/{REVISION}.py"
    spec = importlib.util.spec_from_file_location(REVISION, path)
    assert spec and spec.loader
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    return revision


async def _again(url: str, revision: ModuleType) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as c:
        await c.run_sync(revision.clear)
    await engine.dispose()


def _state(url: str, tenant: str) -> tuple[set[str], list[tuple[str, str]], int]:
    held, audit, version = asyncio.run(
        _run(
            url,
            [
                (
                    "SELECT role_id FROM role_permissions WHERE tenant_id = :t AND area = 'approvals' "
                    "AND action = 'decide'",
                    {"t": tenant},
                ),
                (
                    "SELECT action, target_id FROM audit_entries WHERE tenant_id = :t AND actor = :a",
                    {"t": tenant, "a": f"migration:{REVISION}"},
                ),
                ("SELECT permission_version FROM tenants WHERE id = :t", {"t": tenant}),
            ],
        )
    )
    return {r[0] for r in held}, sorted((a, t) for a, t in audit), version[0][0]


def test_only_admin_holds_approve_own_requests_after_the_revision_with_one_audit_row_per_role(
    database_url: str,
) -> None:
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
        # Admin as seeded, a Builder an admin had edited to hold the cell, and a custom role copied from Admin.
        for role, builtin in (("admin", True), ("builder", True), ("loan_desk", False)):
            writes.append(
                (
                    "INSERT INTO roles (tenant_id, id, name, builtin, description, created_at) "
                    "VALUES (:t, :id, :id, :b, '', :now)",
                    {"t": tenant, "id": role, "b": builtin, "now": now},
                )
            )
            for action in ("view", "decide"):
                writes.append(
                    (
                        "INSERT INTO role_permissions (tenant_id, role_id, area, action, scope) "
                        "VALUES (:t, :r, 'approvals', :x, 'all')",
                        {"t": tenant, "r": role, "x": action},
                    )
                )
        asyncio.run(_run(database_url, writes))
        _, _, version = _state(database_url, tenant)
    finally:
        command.upgrade(alembic_config(), "head")
    held, audit, after = _state(database_url, tenant)
    assert held == {"admin"}
    assert audit == [("role.self_approval", "builder"), ("role.self_approval", "loan_desk")]
    assert after == version + 1
    # A second run finds nothing to clear: no row, no audit entry, no version change.
    asyncio.run(_again(database_url, _revision()))
    assert _state(database_url, tenant) == (held, audit, after)
    # The downgrade puts back what the audit rows name, and the upgrade clears it again.
    command.downgrade(alembic_config(), BEFORE)
    assert _state(database_url, tenant)[0] == {"admin", "builder", "loan_desk"}
    command.upgrade(alembic_config(), "head")
    held, audit_again, _ = _state(database_url, tenant)
    assert held == {"admin"}
    assert len(audit_again) == 4
