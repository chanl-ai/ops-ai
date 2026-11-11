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
        "enabled, input, masked_output, rate_limit_per_min, requires_approval) values (:t, :op, :id, 0, :op, :op, "
        "'', 'write', true, cast('[]' as json), cast('[]' as json), 60, :waits)",
        t=T, id=mid, op=f"{mid}_op", waits=waits,
    )  # fmt: skip


async def _waits(engine: AsyncEngine) -> dict[str, bool]:
    return {
        r["module_id"]: r["requires_approval"]
        for r in await _rows(engine, "select module_id, requires_approval from module_operations")
    }


async def _audit(engine: AsyncEngine) -> list[dict[str, Any]]:
    """The shared audit log's entries (ops_store.audit) the migration recorded in the service outbox, by tool."""
    rows = await _rows(engine, "select tenant_id, payload from service_outbox where name = 'audit.recorded'")
    entries = [{"tenant_id": r["tenant_id"], **r["payload"]} for r in rows]
    return sorted(entries, key=lambda e: e["targetId"])


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


async def test_a_write_saved_before_1_nov_holding_false_is_unchanged() -> None:
    async with scratch_database("tools_write_approvals_old") as target:
        _alembic(target, "upgrade", BEFORE)
        engine = create_async_engine(target)
        try:
            await _write_tool(engine, "mod_old", SAVED_BEFORE, waits=False)
            _alembic(target, "upgrade", AFTER)
            assert await _waits(engine) == {"mod_old": False}
            assert await _audit(engine) == [], "an untouched write has no audit row"
        finally:
            await engine.dispose()


async def test_each_changed_tool_is_recorded_in_the_shared_audit_log_with_its_operation_and_reason() -> None:
    async with scratch_database("tools_write_approvals_audit") as target:
        _alembic(target, "upgrade", BEFORE)
        engine = create_async_engine(target)
        try:
            await _write_tool(engine, "mod_a", SAVED_AFTER, waits=False)
            await _write_tool(engine, "mod_b", SAVED_AFTER, waits=False)
            await _write_tool(engine, "mod_kept", SAVED_AFTER, waits=True)  # already waits: not a change
            await _write_tool(engine, "mod_old", SAVED_BEFORE, waits=False)
            _alembic(target, "upgrade", AFTER)
            entries = await _audit(engine)
            assert [e["targetId"] for e in entries] == ["mod_a_op", "mod_b_op"], entries
            for e in entries:
                assert e["tenant_id"] == T and e["action"] and e["targetKind"], e
                assert e["detail"]["summary"], "the Audit page shows the line"
                assert e["detail"]["moduleId"] == e["targetId"].removesuffix("_op"), "names the tool"
                assert e["detail"]["operationId"] == e["targetId"], "names the operation"
                assert e["detail"]["reason"], "gives the reason"
            tables = {r["table_name"] for r in await _rows(engine, "select table_name from information_schema.tables")}
            assert "operation_audit" not in tables, "a second audit table beside the shared log"
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
            ops = [e["targetId"] for e in await _audit(engine)]
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


async def _chosen_in(zone: str, suffix: str) -> dict[str, bool]:
    """The writes the migration turns on in a database whose session time zone is `zone`, for modules saved either
    side of 1 November 00:00 UTC (a few hours apart, so a zone offset moves them across the cut-off)."""
    async with scratch_database(suffix) as target:
        _alembic(target, "upgrade", BEFORE)
        engine = create_async_engine(target)
        try:
            async with engine.connect() as c:
                autocommit = await c.execution_options(isolation_level="AUTOCOMMIT")
                await autocommit.execute(
                    sa.text(
                        "do $$ begin execute format('alter database %I set timezone to %L', "
                        f"current_database(), '{zone}'); end $$"
                    )
                )
            await _write_tool(engine, "mod_just_after", datetime(2026, 11, 1, 3, 0, tzinfo=UTC), waits=False)
            await _write_tool(engine, "mod_just_before", datetime(2026, 10, 31, 21, 0, tzinfo=UTC), waits=False)
            _alembic(target, "upgrade", AFTER)
            return await _waits(engine)
        finally:
            await engine.dispose()


async def test_the_1_nov_cut_off_picks_the_same_writes_in_any_session_time_zone() -> None:
    in_utc = await _chosen_in("UTC", "tools_wa_utc")
    in_los_angeles = await _chosen_in("America/Los_Angeles", "tools_wa_la")
    assert in_los_angeles == in_utc, (
        f"the cut-off moved with the session zone: UTC {in_utc}, Los Angeles {in_los_angeles}"
    )
