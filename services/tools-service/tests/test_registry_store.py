"""The registry's tables and repository: the migration applies and reverts, the dev seed loads the console's modules,
and a module written from a stale read is refused instead of overwriting the newer one."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.settings import Settings
from ops_tools.modules.seed import aggregates, load
from ops_tools.store.modules import ModuleStore, StaleModuleError

SERVICE = Path(__file__).parents[1]
REGISTRY = {"tool_modules", "module_operations", "module_versions", "security_reviews", "module_approvals"}


async def _tables(url: str) -> set[str]:
    e = create_async_engine(url)
    async with e.connect() as c:
        names: set[str] = await c.run_sync(lambda sync: set(sa.inspect(sync).get_table_names()))
    await e.dispose()
    return names


def _alembic(url: str, *args: str) -> None:
    env = {**os.environ, "OPS_DATABASE_URL": url}
    subprocess.run(["uv", "run", "alembic", *args], cwd=SERVICE, env=env, check=True, capture_output=True)


async def test_migration_applies_and_reverts() -> None:
    # A database of its own: downgrading the shared test database would pull tables from under other tests.
    url = make_url(Settings().database_url)
    scratch = url.set(database=f"{url.database}_tools_migrations")
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        await c.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch.database}"'))
        await c.execute(sa.text(f'CREATE DATABASE "{scratch.database}"'))
    await admin.dispose()
    target = scratch.render_as_string(hide_password=False)

    _alembic(target, "upgrade", "head")
    assert await _tables(target) >= REGISTRY
    _alembic(target, "downgrade", "tools_0001_gateway")
    assert not REGISTRY & await _tables(target)
    _alembic(target, "upgrade", "head")
    assert await _tables(target) >= REGISTRY


async def test_seed_loads_the_console_modules_once(store: ModuleStore, seed: dict[str, Any], tenant: str) -> None:
    now = datetime.now(UTC)
    expected = len(seed["modules"]) + 1  # the mock adds one blank draft
    assert await load(store, seed, tenant_id=tenant, now=now) == expected
    assert await load(store, seed, tenant_id=tenant, now=now) == 0, "a second load adds nothing"
    assert await store.count(tenant) == expected

    core = await store.get(tenant, "mod_core_banking")
    assert core is not None
    assert [o["name"] for o in core["operations"]] == [o["name"] for o in seed["modules"][0]["operations"]]
    found = await store.operation_named(tenant, "get_loan_account")
    assert found is not None and found[0]["id"] == "mod_core_banking"
    assert found[1]["access"] == "read"


async def test_money_movement_always_needs_approval(seed: dict[str, Any]) -> None:
    mods = aggregates(seed, tenant_id="t", now=datetime.now(UTC))
    money = [o for m in mods for o in m["operations"] if o["access"] == "money_movement"]
    assert money, "the seed has money movement operations"
    assert all(o["requires_approval"] for o in money)


async def test_a_stale_write_is_refused(store: ModuleStore, seed: dict[str, Any], tenant: str) -> None:
    agg: dict[str, Any] = {**aggregates(seed, tenant_id=tenant, now=datetime.now(UTC))[0], "egress_hosts": []}
    first = await store.put(agg, expected_revision=None)
    mine = await store.put({**first, "description": "edited by A"}, expected_revision=first["revision"])
    with pytest.raises(StaleModuleError):
        await store.put({**first, "description": "edited by B from the old read"}, expected_revision=first["revision"])
    stored = await store.get(tenant, agg["id"])
    assert stored is not None
    assert (stored["description"], stored["revision"]) == ("edited by A", mine["revision"])
    assert len(stored["operations"]) == len(agg["operations"]), "children are replaced, not duplicated"


async def test_a_changed_seed_reaches_untouched_modules_and_spares_edited_ones(
    store: ModuleStore, seed: dict[str, Any], tenant: str
) -> None:
    now = datetime.now(UTC)
    await load(store, seed, tenant_id=tenant, now=now)
    edited = await store.get(tenant, "mod_core_banking")
    assert edited is not None
    await store.put({**edited, "description": "edited by a person"}, expected_revision=edited["revision"])

    changed = json.loads(json.dumps(seed))
    for m in changed["modules"]:
        m["description"] = "the seed changed"
    await load(store, changed, tenant_id=tenant, now=now)
    core, cards = await store.get(tenant, "mod_core_banking"), await store.get(tenant, "mod_card_platform")
    assert core is not None and cards is not None
    assert core["description"] == "edited by a person"
    assert cards["description"] == "the seed changed"
