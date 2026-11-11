"""tools_0072 makes every tool write saved since 2026-11-01 wait for approval, by failure mode: a write saved on or
after that day that holds requires_approval=false still runs unattended; an earlier write is changed too, so a team's
deliberate setting is overridden; a changed write leaves no audit row, or a row that names no tool or reason; a second
run changes rows or writes audit again; and an admin can no longer switch a write back to false afterwards."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_tools.store.modules import ModuleStore

from .test_registry_store import _alembic, scratch_database  # pyright: ignore[reportPrivateUsage]

BEFORE = "tools_0071_account_key"
AFTER = "tools_0072_write_approvals_on"
T = "t_wa"
SAVED_AFTER = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
SAVED_BEFORE = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)


async def _sql(engine: AsyncEngine, statement: str, **values: Any) -> None:
    async with engine.begin() as c:
        await c.execute(sa.text(statement), values)


async def _rows(engine: AsyncEngine, query: str) -> list[dict[str, Any]]:
    async with engine.connect() as c:
        return [dict(r) for r in (await c.execute(sa.text(query))).mappings()]


async def _write_tool(engine: AsyncEngine, mid: str, saved: datetime, *, waits: bool) -> None:
    """A module saved at `saved` with one write operation; the module's save time is when the write was saved."""
    await _sql(
        engine,
        "insert into tool_modules (tenant_id, id, team_id, name, display_name, system, description, status, "
        "owner_team, owner_contacts, auth, timeout_ms, data_classification, reachable, drift, version, "
        "pending, revision, created_at, updated_at) values (:t, :id, 'team_a', :id, :id, 'sys', '', "
        "'active', 'team_a', cast('[]' as json), cast('{}' as json), 5000, 'internal', true, "
        "false, '1.0', cast('[]' as json), 1, :at, :at)",
        t=T, id=mid, at=saved,
    )  # fmt: skip
    await _sql(
        engine,
        "insert into module_operations (tenant_id, id, module_id, position, name, tool_id, description, access, "
        "enabled, input, masked_output, rate_limit_per_min, requires_approval, stub, seed_calls24h, seed_error_rate, "
        "seed_p95_ms) values (:t, :op, :id, 0, :op, :op, '', 'write', true, cast('[]' as json), cast('[]' as json), "
        "60, :waits, cast('{}' as json), 0, 0, 0)",
        t=T, id=mid, op=f"{mid}_op", waits=waits,
    )  # fmt: skip


async def _waits(engine: AsyncEngine) -> dict[str, bool]:
    return {
        r["module_id"]: r["requires_approval"]
        for r in await _rows(engine, "select module_id, requires_approval from module_operations")
    }


async def _audit(engine: AsyncEngine) -> list[dict[str, Any]]:
    return await _rows(engine, "select * from operation_audit order by operation_id")


async def test_a_write_saved_since_1_nov_holding_false_waits_and_an_earlier_one_is_untouched() -> None:
    async with scratch_database("tools_write_approvals") as target:
        _alembic(target, "upgrade", BEFORE)
        engine = create_async_engine(target)
        try:
            await _write_tool(engine, "mod_new", SAVED_AFTER, waits=False)
            await _write_tool(engine, "mod_old", SAVED_BEFORE, waits=False)
            _alembic(target, "upgrade", AFTER)
            assert await _waits(engine) == {"mod_new": True, "mod_old": False}
        finally:
            await engine.dispose()


async def test_one_audit_row_per_changed_tool_names_the_tool_and_the_reason() -> None:
    async with scratch_database("tools_write_approvals_audit") as target:
        _alembic(target, "upgrade", BEFORE)
        engine = create_async_engine(target)
        try:
            await _write_tool(engine, "mod_a", SAVED_AFTER, waits=False)
            await _write_tool(engine, "mod_b", SAVED_AFTER, waits=False)
            await _write_tool(engine, "mod_kept", SAVED_AFTER, waits=True)  # already waits: not a change
            await _write_tool(engine, "mod_old", SAVED_BEFORE, waits=False)
            _alembic(target, "upgrade", AFTER)
            rows = await _audit(engine)
            assert [r["operation_id"] for r in rows] == ["mod_a_op", "mod_b_op"], rows
            for r in rows:
                assert r["tenant_id"] == T and r["reason"], "a row names the tenant and gives the reason"
                assert r["module_id"] == r["operation_id"].removesuffix("_op")
        finally:
            await engine.dispose()


async def test_running_the_migration_twice_changes_nothing_the_second_time() -> None:
    async with scratch_database("tools_write_approvals_twice") as target:
        _alembic(target, "upgrade", BEFORE)
        engine = create_async_engine(target)
        try:
            await _write_tool(engine, "mod_new", SAVED_AFTER, waits=False)
            _alembic(target, "upgrade", AFTER)
            first = await _waits(engine)
            _alembic(target, "downgrade", BEFORE)
            _alembic(target, "upgrade", AFTER)
            assert await _waits(engine) == first
            ops = [r["operation_id"] for r in await _audit(engine)]
            assert ops == ["mod_new_op"], f"the second run wrote audit again: {ops}"
        finally:
            await engine.dispose()


async def test_an_admin_switching_a_write_back_to_false_after_the_migration_sticks() -> None:
    async with scratch_database("tools_write_approvals_back") as target:
        _alembic(target, "upgrade", BEFORE)
        engine = create_async_engine(target)
        try:
            await _write_tool(engine, "mod_new", SAVED_AFTER, waits=False)
            _alembic(target, "upgrade", AFTER)
            assert await _waits(engine) == {"mod_new": True}
            store = ModuleStore(engine)
            module = await store.get(T, "mod_new")
            assert module is not None
            module["operations"][0]["requires_approval"] = False
            await store.put(module, expected_revision=module["revision"])
            assert await _waits(engine) == {"mod_new": False}
            _alembic(target, "upgrade", "head")
            assert await _waits(engine) == {"mod_new": False}, "later migrations or a re-run put the setting back"
        finally:
            await engine.dispose()
