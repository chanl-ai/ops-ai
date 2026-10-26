"""The registry's tables and repository: the migration applies and reverts, the dev seed loads the console's modules,
and a module written from a stale read is refused instead of overwriting the newer one."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.settings import Settings
from ops_store.team_scope import acting_as
from ops_tools.modules.seed import aggregates, blank, load
from ops_tools.store.modules import ModuleStore, RetiredAccessError, StaleModuleError

SERVICE = Path(__file__).parents[1]
REGISTRY = {"tool_modules", "module_operations", "module_versions", "module_approvals"}


async def _tables(url: str) -> set[str]:
    e = create_async_engine(url)
    async with e.connect() as c:
        names: set[str] = await c.run_sync(lambda sync: set(sa.inspect(sync).get_table_names()))
    await e.dispose()
    return names


def _alembic(url: str, *args: str) -> None:
    env = {**os.environ, "OPS_DATABASE_URL": url}
    subprocess.run(["uv", "run", "alembic", *args], cwd=SERVICE, env=env, check=True, capture_output=True)


@asynccontextmanager
async def scratch_database(suffix: str) -> AsyncGenerator[str]:
    """A database of its own for a migration test, dropped at the end so runs leave nothing behind."""
    url = make_url(Settings().database_url)
    scratch = url.set(database=f"{url.database}_{suffix}")
    admin = create_async_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        await c.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch.database}" WITH (FORCE)'))
        await c.execute(sa.text(f'CREATE DATABASE "{scratch.database}"'))
    try:
        yield scratch.render_as_string(hide_password=False)
    finally:
        async with admin.connect() as c:
            await c.execute(sa.text(f'DROP DATABASE IF EXISTS "{scratch.database}" WITH (FORCE)'))
        await admin.dispose()


async def test_migration_applies_and_reverts() -> None:
    # A database of its own: downgrading the shared test database would pull tables from under other tests.
    async with scratch_database("tools_migrations") as target:
        _alembic(target, "upgrade", "head")
        assert await _tables(target) >= REGISTRY
        _alembic(target, "downgrade", "tools_0001_gateway")
        assert not REGISTRY & await _tables(target)
        _alembic(target, "upgrade", "head")
        assert await _tables(target) >= REGISTRY


async def test_seed_loads_the_console_modules_once(store: ModuleStore, seed: dict[str, Any], tenant: str) -> None:
    now = datetime.now(UTC)
    # The mock adds one blank draft; every tenant has the Runtime module, which holds the platform's own tools.
    expected = len(seed["modules"]) + 2
    assert await load(store, seed, tenant_id=tenant, now=now) == expected
    assert await load(store, seed, tenant_id=tenant, now=now) == 0, "a second load adds nothing"
    assert await store.count(tenant) == expected

    core = await store.get(tenant, "mod_core_banking")
    assert core is not None
    assert [o["name"] for o in core["operations"]] == [o["name"] for o in seed["modules"][0]["operations"]]
    found = await store.operation_named(tenant, "get_loan_account")
    assert found is not None and found[0]["id"] == "mod_core_banking"
    assert found[1]["access"] == "read"


async def test_two_teams_in_one_tenant_each_own_a_module_of_the_same_name(store: ModuleStore, tenant: str) -> None:
    now = datetime.now(UTC)

    def module(team: str, module_id: str) -> dict[str, Any]:
        row = blank(
            module_id=module_id,
            tenant_id=tenant,
            team_id=team,
            owner="Ops",
            me="seed",
            at=now,
            input={"displayName": "Shared bank", "name": "shared-bank", "type": "http"},
        )
        row["operations"] = [
            {
                "id": f"{module_id}_op1",
                "tool_id": "tl_search",
                "name": "search_customers",
                "description": "Find a customer",
                "access": "read",
                "enabled": True,
                "executor": "stub",
                "method": None,
                "path": None,
                "headers": [],
                "body": None,
                "input": [],
                "masked_output": [],
                "binding": None,
                "rate_limit_per_min": 60,
                "requires_approval": False,
                "amount_max": None,
                "stub": {"ok": True},
            }
        ]
        return row

    await store.put(module("team_a", "mod_a"), expected_revision=None)
    await store.put(module("team_b", "mod_b"), expected_revision=None)
    with acting_as("team_a"):
        assert (await store.get(tenant, "mod_a")) is not None
        assert (await store.get(tenant, "mod_b")) is None
        found = await store.operation_named(tenant, "search_customers")
        assert found is not None and found[0]["id"] == "mod_a"
        assert "shared-bank" in await store.names(tenant)
    with acting_as("team_b"):
        assert (await store.get(tenant, "mod_b")) is not None
        assert (await store.get(tenant, "mod_a")) is None
        found = await store.operation_named(tenant, "search_customers")
        assert found is not None and found[0]["id"] == "mod_b"


async def test_the_seed_has_only_read_and_write_and_two_approver_writes_need_approval(seed: dict[str, Any]) -> None:
    ops = [o for m in aggregates(seed, tenant_id="t", now=datetime.now(UTC)) for o in m["operations"]]
    assert {o["access"] for o in ops} == {"read", "write"}
    two = [o for o in ops if o["approvers"] == 2]
    assert {"place_wire_hold", "transfer_funds", "issue_provisional_credit"} <= {o["name"] for o in two}
    assert all(o["requires_approval"] for o in two)


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


async def test_a_retired_access_class_is_refused_when_read_and_its_database_rebuilt(seed: dict[str, Any]) -> None:
    """A database built before Read and Write only (tools_0011) and holding a money_movement row: `make up` sees its
    chain behind the code's head and rebuilds it, and migrating it in place (KEEP_DATA=1) fails on the row instead of
    keeping one the code refuses to read (c-048 T003)."""
    async with scratch_database("tools_retired_access") as target:
        # A database from before tools_0012, as `make up` meets one: written at head, then the CHECK taken away, one row
        # set back to money_movement, and the tools chain recorded at tools_0011.
        _alembic(target, "upgrade", "head")
        engine = create_async_engine(target)
        agg: dict[str, Any] = {**aggregates(seed, tenant_id="t", now=datetime.now(UTC))[0], "egress_hosts": []}
        await ModuleStore(engine).put(agg, expected_revision=None)
        async with engine.begin() as c:
            await c.execute(sa.text("ALTER TABLE module_operations DROP CONSTRAINT ck_module_operations_access"))
            await c.execute(
                sa.text("UPDATE module_operations SET access = 'money_movement' WHERE id = :id"),
                {"id": agg["operations"][0]["id"]},
            )
            await c.execute(sa.text("UPDATE alembic_version_tools SET version_num = 'tools_0011_approval_policy'"))
        # Read, the row is refused, never treated as a read.
        with pytest.raises(RetiredAccessError, match="money_movement"):
            await ModuleStore(engine).get("t", agg["id"])
        await engine.dispose()

        # scripts/schema_sync.py's rule: a chain whose recorded version is not the code's head is rebuilt by `make up`.
        engine = create_async_engine(target)
        async with engine.connect() as c:
            recorded = (await c.execute(sa.text("SELECT version_num FROM alembic_version_tools"))).scalar()
        await engine.dispose()
        head = ScriptDirectory.from_config(Config(str(SERVICE / "alembic.ini"))).get_current_head()
        assert recorded == "tools_0011_approval_policy" and head != recorded, "make up rebuilds it"
        with pytest.raises(subprocess.CalledProcessError) as kept:
            _alembic(target, "upgrade", "head")
        assert b"ck_module_operations_access" in kept.value.stderr
