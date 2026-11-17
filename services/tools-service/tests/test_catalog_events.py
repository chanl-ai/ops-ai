"""The catalogue events agents-service keeps its copy of the tools by, by failure mode: a module write that changes
what a tools list shows and reports nothing, reports twice, or reports a revision that does not rise; a write that
changes nothing a list shows reported anyway; a grant to another team started, changed or ended with no event for
that team; an event written apart from its change, so a write that rolls back still reports; one tenant's write
reported as, or beside, another's; and a module too large for one event sent whole, which its receiver refuses
forever."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import isolation
from ops_tools.modules.seed import load
from ops_tools.store.modules import Aggregate, ModuleStore, StaleModuleError, service_outbox

MODULE = "mod_core_banking"
Change = Callable[[Aggregate], Aggregate]


async def _reported(engine: AsyncEngine, tenant: str) -> list[dict[str, Any]]:
    """The tenant's catalogue events, oldest first, with the outbox row's tenant, team, name and key."""
    o = service_outbox.c
    q = sa.select(service_outbox).where(o.tenant_id == tenant, o.name.like("tool.%")).order_by(o.created_at, o.id)
    async with engine.connect() as c:
        return [dict(r) for r in (await c.execute(q)).mappings()]


async def _loaded(engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog: list[dict[str, Any]]) -> Aggregate:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog)
    module = await ModuleStore(engine).get(tenant, MODULE)
    assert module is not None
    return module


def _renamed(m: Aggregate) -> Aggregate:
    return {**m, "operations": [{**o, "name": f"{o['name']}_v2"} for o in m["operations"]]}


def _granted(m: Aggregate) -> Aggregate:
    """A new approved grant to a team that held none."""
    first = m["approvals"][0]
    return {**m, "approvals": [*m["approvals"], {**first, "id": "apr_new", "workflow_team_id": "team_new"}]}


def _revoked(m: Aggregate) -> Aggregate:
    """Every approval of the first granted team revoked."""
    team = next(a["workflow_team_id"] for a in m["approvals"] if a["status"] == "approved")
    ended = [{**a, "status": "revoked"} if a["workflow_team_id"] == team else a for a in m["approvals"]]
    return {**m, "approvals": ended}


# (write, what it changes, the events it reports as (name, team or "owner", deleted)).
CASES: list[tuple[str, Change | None, list[tuple[str, str, bool]]]] = [
    ("operations renamed", _renamed, [("tool.module.changed", "owner", False)]),
    ("new version", lambda m: {**m, "version": "9.0.0"}, [("tool.module.published", "owner", False)]),
    ("description only", lambda m: {**m, "description": "Nothing a tools list shows."}, []),
    (
        "operation described",
        lambda m: {**m, "operations": [{**o, "description": "Shown in the tool picker."} for o in m["operations"]]},
        [("tool.module.changed", "owner", False)],
    ),
    ("grant to a new team", _granted, [("tool.team_state.changed", "team_new", False)]),
    ("grant revoked", _revoked, [("tool.team_state.changed", "revoked", True)]),
    ("module deleted", None, [("tool.module.changed", "owner", True), ("tool.team_state.changed", "granted", True)]),
]


Case = tuple[str, Change | None, list[tuple[str, str, bool]]]


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
async def test_each_write_reports_once_what_it_changed_at_the_next_revision(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]], case: Case
) -> None:
    write, change, expected = case
    module = await _loaded(engine, seed, tenant, catalog_tools)
    before = len(await _reported(engine, tenant))
    store = ModuleStore(engine)
    granted = sorted({a["workflow_team_id"] for a in module["approvals"] if a["status"] == "approved"})
    if change is None:
        assert await store.delete(tenant, MODULE)
    else:
        await store.put(change(module), expected_revision=module["revision"])
    events = (await _reported(engine, tenant))[before:]
    first = next(a["workflow_team_id"] for a in module["approvals"] if a["status"] == "approved")
    teams = {"owner": module["team_id"], "revoked": first}
    want = [
        (name, t, deleted)
        for name, team, deleted in expected
        for t in (granted if team == "granted" else [teams.get(team, team)])
    ]
    assert [(e["name"], e["team_id"], e["payload"]["deleted"]) for e in events] == want, write
    rising = module["revision"] + 1
    assert {e["payload"]["revision"] for e in events} <= {rising}, "every event carries the write's new revision"
    assert len({(e["team_id"], e["event_key"]) for e in events}) == len(events), "no two events share a key"
    if write == "operations renamed":
        assert {o["name"] for o in events[0]["payload"]["operations"]} == {
            f"{o['name']}_v2" for o in module["operations"]
        }


async def test_a_write_that_rolls_back_or_loses_its_race_reports_nothing(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> None:
    module = await _loaded(engine, seed, tenant, catalog_tools)
    before = await _reported(engine, tenant)
    store = ModuleStore(engine)
    with pytest.raises(StaleModuleError):
        await store.put(_renamed(module), expected_revision=module["revision"] - 1)
    with pytest.raises(RuntimeError, match="after the write"):
        async with store.tx() as c:
            await store.put(_renamed(module), expected_revision=module["revision"], conn=c)
            raise RuntimeError("after the write")
    assert await _reported(engine, tenant) == before


async def test_a_tenants_write_reports_for_that_tenant_only(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> None:
    other = f"t_{uuid4().hex[:10]}"
    with isolation.tenant_wide("TESTS", tenant_id=other):
        await _loaded(engine, seed, other, catalog_tools)
    theirs = await _reported(engine, other)
    module = await _loaded(engine, seed, tenant, catalog_tools)
    before = len(await _reported(engine, tenant))
    await ModuleStore(engine).put(_renamed(module), expected_revision=module["revision"])
    [event] = (await _reported(engine, tenant))[before:]
    assert event["tenant_id"] == tenant
    assert await _reported(engine, other) == theirs, "nothing reported under the other tenant"


async def test_a_module_too_large_for_one_event_is_reported_truncated_without_operations(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> None:
    module = await _loaded(engine, seed, tenant, catalog_tools)
    first = module["operations"][0]
    many = [{**first, "id": f"op_{i}", "name": f"tool_{i}", "description": "x" * 400} for i in range(300)]
    before = len(await _reported(engine, tenant))
    await ModuleStore(engine).put({**module, "operations": many}, expected_revision=module["revision"])
    [event] = (await _reported(engine, tenant))[before:]
    assert (event["payload"]["truncated"], event["payload"]["operations"]) == (True, [])
