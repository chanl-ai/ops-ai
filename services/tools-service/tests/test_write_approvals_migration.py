"""tools_0072 sets every stored requires_approval=false to not set (NULL), at any date, so the team default decides, by
failure mode: an off write still runs unattended; an older off is skipped because of its date; a write that already
waits is changed; a changed write leaves no audit row, or one that names no tool or reason; a second run changes rows
or writes audit again; an admin's off after the migration is put back; a newly created tool stores off instead of not
set; and a not-set write runs at once or waits regardless of the team default."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_tools.modules.policy import WriteApprovals
from ops_tools.store.modules import ModuleStore

from .conftest import Api
from .fake_upstream import ENDPOINT, HOST
from .test_registry_store import _alembic, scratch_database  # pyright: ignore[reportPrivateUsage]
from .test_write_approval_gateway import ADDRESS, Call, _gateway, reasons  # pyright: ignore[reportPrivateUsage]

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


async def _waits(engine: AsyncEngine) -> dict[str, bool | None]:
    return {
        r["module_id"]: r["requires_approval"]
        for r in await _rows(engine, "select module_id, requires_approval from module_operations")
    }


async def _audit(engine: AsyncEngine) -> list[dict[str, Any]]:
    """The shared audit log's entries (ops_store.audit) the migration recorded in the service outbox, by tool."""
    rows = await _rows(engine, "select tenant_id, payload from service_outbox where name = 'audit.recorded'")
    entries = [{"tenant_id": r["tenant_id"], **r["payload"]} for r in rows]
    return sorted(entries, key=lambda e: e["targetId"])


async def test_every_stored_off_becomes_not_set_whatever_its_date_and_a_write_that_waits_is_left() -> None:
    async with scratch_database("tools_write_approvals") as target:
        _alembic(target, "upgrade", BEFORE)
        engine = create_async_engine(target)
        try:
            await _write_tool(engine, "mod_new", SAVED_AFTER, waits=False)
            await _write_tool(engine, "mod_old", SAVED_BEFORE, waits=False)
            await _write_tool(engine, "mod_on", SAVED_BEFORE, waits=True)
            _alembic(target, "upgrade", AFTER)
            assert await _waits(engine) == {"mod_new": None, "mod_old": None, "mod_on": True}
        finally:
            await engine.dispose()


async def test_a_write_saved_30_oct_holding_off_is_audited_like_any_other() -> None:
    async with scratch_database("tools_write_approvals_old") as target:
        _alembic(target, "upgrade", BEFORE)
        engine = create_async_engine(target)
        try:
            await _write_tool(engine, "mod_old", SAVED_BEFORE, waits=False)
            _alembic(target, "upgrade", AFTER)
            assert await _waits(engine) == {"mod_old": None}
            assert [e["targetId"] for e in await _audit(engine)] == ["mod_old_op"]
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
            assert [e["targetId"] for e in entries] == ["mod_a_op", "mod_b_op", "mod_old_op"], entries
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
            assert first == {"mod_new": None}
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
            assert await _waits(engine) == {"mod_new": None}
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


async def test_a_newly_created_tool_stores_not_set_not_off(bank_api: Api, engine: AsyncEngine) -> None:
    """An imported write, created with no approval setting, keeps none: a later change of the team default then
    reaches it without a migration."""
    r = await bank_api.client.post("/v1/egress/hosts", json={"value": HOST})
    assert r.status_code in (200, 201), r.text
    hold: dict[str, Any] = {"name": "place_hold", "description": "", "access": "write", "group": "x", "input": []}
    r = await bank_api.call(
        "POST",
        "/mod_document_service/operations/import",
        json={"source": {"kind": "openapi", "specUrl": f"{ENDPOINT}/openapi.json"}, "operations": [hold]},
    )
    assert r.status_code == 200, r.text
    rows = await _rows(
        engine,
        "select requires_approval from module_operations "
        f"where tenant_id = '{bank_api.tenant}' and name = 'place_hold'",
    )
    assert [r["requires_approval"] for r in rows] == [None], rows


class TeamDefault(WriteApprovals):
    """The team's appsChangeWithoutAsking, read live: empty until `loosened` (the app's writes then run at once)."""

    loosened = False

    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__(cast(Any, None))
        self.engine = engine

    async def all_writes(self, tenant_id: str, team_id: str | None) -> bool:
        return False

    async def apps(self, tenant_id: str, team_id: str | None) -> list[str] | None:
        return []

    async def change_without_asking(self, tenant_id: str, team_id: str | None) -> list[str] | None:
        if not self.loosened:
            return []
        mods = await ModuleStore(self.engine).all_teams(tenant_id)
        return [f"module:{m['id']}" for m in mods if any(o["name"] == "update_address" for o in m["operations"])]


@pytest.fixture
async def team_default_gateway(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[tuple[Call, TeamDefault]]:
    default = TeamDefault(engine)
    async for call in _gateway(engine, seed, tenant, catalog_tools, default):
        await _sql(
            engine,
            "update module_operations set requires_approval = null where tenant_id = :t and name = 'update_address'",
            t=tenant,
        )
        yield call, default


async def test_a_not_set_write_waits_by_default_and_runs_at_once_when_the_team_default_is_loosened(
    team_default_gateway: tuple[Call, TeamDefault],
) -> None:
    call, default = team_default_gateway
    waits = await call("update_address", ADDRESS, "unset-1")
    assert (waits.status_code, reasons(waits)) == (403, ["write needs an approval token"]), waits.text
    default.loosened = True
    runs = await call("update_address", ADDRESS, "unset-2")
    assert runs.status_code == 200 and runs.json()["data"]["decision"] == "allow", runs.text
