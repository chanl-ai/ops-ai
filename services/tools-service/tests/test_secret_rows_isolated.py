"""Sealed secret values are held by the database (proved across every locked table in C5), by failure mode:
another team reads a team's tool secrets or their audit through the store; another team, or another tenant for Ops
AI's own app secrets, reads or changes them with SQL that names no team, which only the database policy can stop.
Runs on the compose PostgreSQL as `ops_tools_tenant`, the role every store transaction runs as, since the database
user the tests connect as bypasses row security."""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import isolation
from ops_store.schema import isolation_kind
from ops_tools.store.plugin_app_keys import plugin_app_keys
from ops_tools.store.secrets import SecretStore, secret_audit, tool_secrets

ROLE = "ops_tools_tenant"
TEAM_A, TEAM_B = "team_cards", "team_ops"


async def _sealed(engine: AsyncEngine, tenant: str) -> SecretStore:
    """Team A's secret with its audit row, and the account's app secret for a plugin."""
    store = SecretStore(engine)
    with isolation.scope(tenant, TEAM_A):
        await store.create(tenant, TEAM_A, "DESK_KEY", "sealed-a", actor="t", at=datetime.now(UTC))
    async with engine.begin() as c:
        await c.execute(
            plugin_app_keys.insert().values(
                tenant_id=tenant, plugin_id="test.desk", ciphertext="sealed-app", updated_by="t", updated_at="t"
            )
        )
    return store


async def test_another_team_finds_no_secret_through_the_store(engine: AsyncEngine, tenant: str) -> None:
    store = await _sealed(engine, tenant)
    with isolation.scope(tenant, TEAM_B):
        assert await store.listed(tenant, TEAM_A) == []
    with isolation.scope(tenant, TEAM_A):
        assert [s["name"] for s in await store.listed(tenant, TEAM_A)] == ["DESK_KEY"]


async def test_the_database_alone_hides_and_guards_them(engine: AsyncEngine, tenant: str) -> None:
    assert [isolation_kind(t) for t in (tool_secrets, secret_audit, plugin_app_keys)] == ["team", "team", "tenant"]
    await _sealed(engine, tenant)
    with isolation.scope(tenant, TEAM_B):
        async with isolation.isolated_tx(engine, role=ROLE) as c:
            for name in ("tool_secrets", "secret_audit"):
                seen = await c.execute(sa.text(f"SELECT count(*) FROM {name} WHERE tenant_id = :t"), {"t": tenant})
                assert seen.scalar_one() == 0, f"team B read {name}"
            changed = await c.execute(
                sa.text("UPDATE tool_secrets SET version = version WHERE tenant_id = :t"), {"t": tenant}
            )
            assert changed.rowcount == 0, "team B changed team A's secret"
    with isolation.scope("t_elsewhere", TEAM_A):
        async with isolation.isolated_tx(engine, role=ROLE) as c:
            seen = await c.execute(sa.text("SELECT count(*) FROM plugin_app_keys WHERE plugin_id = 'test.desk'"))
            assert seen.scalar_one() == 0, "another tenant read the account's app secret"
    with isolation.scope(tenant, TEAM_A):
        async with isolation.isolated_tx(engine, role=ROLE) as c:
            for name, rows in (("tool_secrets", 1), ("secret_audit", 1), ("plugin_app_keys", 1)):
                seen = await c.execute(sa.text(f"SELECT count(*) FROM {name} WHERE tenant_id = :t"), {"t": tenant})
                assert seen.scalar_one() == rows, name
