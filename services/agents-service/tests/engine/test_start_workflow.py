"""Start workflow's host (c-209) on the real database under tenant RLS, by failure mode: a parent's children start in
another team, in live mode from a test run, on a version that is not live or while paused, more than once for a key,
without end when a workflow starts itself, or for a run with no team. The first test drives a parent run through the
real worker into the host. The last two are the run's status: a parent reads succeeded while a child still waits on a
person, or an End meant for a failure reads succeeded."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any, cast
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.api.engine_runs import MAX_CHILD_DEPTH, WorkflowStarts, start_run
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.ports import RunRefusedError
from ops_engine.store import DefinitionStore, RunStore, WorkQueue
from tests.engine.test_worker import (  # noqa: F401
    CountingTools,  # pyright: ignore[reportUnusedImport]
    drain,  # pyright: ignore[reportUnusedImport]
    engine,  # pyright: ignore[reportUnusedImport]
    worker,  # pyright: ignore[reportUnusedImport]
)

TEAM, OTHER = "team_a", "team_b"


def intake(start: dict[str, Any]) -> Any:
    return parse(
        {
            "schemaVersion": 2,
            "id": "intake",
            "name": "Intake",
            "nodes": [
                {"id": "in", "type": "ops.trigger.request", "typeVersion": 1, "name": "Request"},
                {"id": "open", "type": "ops.action.workflow", "typeVersion": 1, "name": "Open", "parameters": start},
                {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {}},
                {"id": "failed", "type": "ops.flow.end", "typeVersion": 1, "name": "Failed", "parameters": {}},
            ],
            "connections": [
                {"from": {"node": "in", "port": "payload"}, "to": {"node": "open", "port": "in"}},
                {"from": {"node": "open", "port": "started"}, "to": {"node": "done", "port": "in"}},
                {"from": {"node": "open", "port": "error"}, "to": {"node": "failed", "port": "in"}},
            ],
        }
    )


CASE = parse(
    {
        "schemaVersion": 2,
        "id": "case",
        "name": "Case",
        "nodes": [
            {"id": "in", "type": "ops.trigger.request", "typeVersion": 1, "name": "Request"},
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {"outcome": "open"}},
        ],
        "connections": [{"from": {"node": "in", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
    }
)
PER_PERSON = {"workflow": "case", "forEach": "$.input.persons", "input": {"name": "$.item.name"}}


class Tenant:
    def __init__(self, db: AsyncEngine) -> None:
        self.id = f"t-{uuid4().hex[:8]}"
        self.tx = EngineTransactions(db)
        self.runs, self.definitions = RunStore(self.tx), DefinitionStore(self.tx)
        self.starts = WorkflowStarts(self.runs, self.definitions)

    async def publish(self, d: Any, *, team: str | None = TEAM, stage: str = "live") -> dict[str, Any]:
        with tenant_scope(self.id):
            version, _ = await self.definitions.publish(
                d.id, name=d.name, definition=d.wire(), digest=d.digest(), now="now", by="b@x", team=team, stage=stage
            )
            return await self.definitions.get(d.id, version) or {}

    async def parent(self, *, mode: str = "live", team: str = TEAM, created_by: str = "b@x") -> str:
        stored = await self.publish(intake(PER_PERSON), team=team or TEAM)
        with tenant_scope(self.id):
            run, _ = await start_run(
                self.runs,
                stored,
                team_id=team,
                mode=cast(Any, mode),
                input={"persons": [{"name": "Ana"}, {"name": "Bo"}, {"name": "Cy"}]},
                run_key=None,
                created_by=created_by,
            )
            return str(run["id"])

    async def start(self, parent: str, key: str = "k:open:1:0") -> Any:
        with tenant_scope(self.id):
            return await self.starts.start(parent, "case", {"name": "Ana"}, key)

    async def children(self) -> list[dict[str, Any]]:
        with tenant_scope(self.id):
            return await self.runs.list(workflow_id="case")


@pytest.fixture
async def tenants(engine: AsyncEngine) -> AsyncIterator[Callable[[], Tenant]]:  # noqa: F811
    """New tenants, whose unfinished runs are cancelled at the end: a queued run left behind would be claimed by the
    next worker test on this database."""
    made: list[Tenant] = []

    def make() -> Tenant:
        made.append(Tenant(engine))
        return made[-1]

    yield make
    for t in made:
        with tenant_scope(t.id):
            for r in await t.runs.list():
                await t.runs.cancel(str(r["id"]), reason="test_ended")


async def refused(t: Tenant, parent: str) -> str:
    with pytest.raises(RunRefusedError) as e:
        await t.start(parent)
    assert await t.children() == []
    return e.value.code


async def test_a_parent_run_starts_one_live_child_per_item_in_its_team_once(
    engine: AsyncEngine,  # noqa: F811
    tenants: Callable[[], Tenant],
) -> None:
    t = tenants()
    await t.publish(CASE)
    parent = await t.parent()
    w = worker(engine, CountingTools(), InMemorySaver())
    w.host.ports.runs = t.starts
    await drain(w)
    children = sorted(await t.children(), key=lambda r: str(r["run_key"]))
    assert [c["input"] for c in children] == [{"name": "Ana"}, {"name": "Bo"}, {"name": "Cy"}]
    assert {(c["team_id"], c["mode"], c["created_by"], c["status"]) for c in children} == {
        (TEAM, "live", f"run:{parent}", "succeeded")
    }
    with tenant_scope(t.id):
        assert (await t.runs.get(parent) or {})["status"] == "succeeded"
    # The same step key again (a retry, a re-run) finds the first child.
    again = await t.start(parent, f"{parent}:open:1:0")
    assert again.created is False and again.run_id in {c["id"] for c in children}
    assert len(await t.children()) == 3


async def test_a_test_parent_starts_test_children_on_the_latest_version(tenants: Callable[[], Tenant]) -> None:
    t = tenants()
    await t.publish(CASE, stage="draft")
    started = await t.start(await t.parent(mode="test"))
    [child] = await t.children()
    assert started.created and child["mode"] == "test" and child["id"] == started.run_id
    assert await refused(tenants(), "nope") == "parent_gone"


async def test_a_live_parent_never_starts_a_draft_or_a_paused_workflow(tenants: Callable[[], Tenant]) -> None:
    t = tenants()
    await t.publish(CASE, stage="draft")
    parent = await t.parent()
    assert await refused(t, parent) == "not_live"
    p = tenants()
    await p.publish(CASE)
    with tenant_scope(p.id):
        await p.definitions.set_paused("case", True)
    assert await refused(p, await p.parent()) == "workflow_paused"


async def test_another_teams_workflow_is_not_found(tenants: Callable[[], Tenant]) -> None:
    t = tenants()
    await t.publish(CASE, team=OTHER)
    assert await refused(t, await t.parent()) == "not_found"


async def test_runs_started_by_runs_stop_at_the_depth_limit(tenants: Callable[[], Tenant]) -> None:
    t = tenants()
    await t.publish(CASE)
    run = await t.parent()
    for _ in range(MAX_CHILD_DEPTH - 1):
        run = await t.parent(created_by=f"run:{run}")
    assert (await t.start(run)).created  # depth limit - 1 above it: still starts
    deeper = await t.parent(created_by=f"run:{run}")
    with pytest.raises(RunRefusedError) as e:
        await t.start(deeper, "k2")
    assert e.value.code == "too_deep"


async def test_a_run_with_no_team_starts_nothing(tenants: Callable[[], Tenant]) -> None:
    t = tenants()
    await t.publish(CASE, team=None)
    assert await refused(t, await t.parent(team="")) == "no_team"


REVIEWED_CASE = parse(
    {
        "schemaVersion": 2,
        "id": "case",
        "name": "Case",
        "nodes": [
            {"id": "in", "type": "ops.trigger.request", "typeVersion": 1, "name": "Request"},
            {
                "id": "ask",
                "type": "ops.flow.humanReview",
                "typeVersion": 1,
                "name": "Ask",
                "parameters": {"title": "Ok?"},
            },
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {"outcome": "open"}},
        ],
        "connections": [
            {"from": {"node": "in", "port": "payload"}, "to": {"node": "ask", "port": "in"}},
            {"from": {"node": "ask", "port": "approve"}, "to": {"node": "done", "port": "in"}},
            {"from": {"node": "ask", "port": "reject"}, "to": {"node": "done", "port": "in"}},
        ],
    }
)


async def test_a_parent_waits_while_a_run_it_started_waits_on_a_person_and_succeeds_when_the_last_ends(
    engine: AsyncEngine,  # noqa: F811
    tenants: Callable[[], Tenant],
) -> None:
    t = tenants()
    await t.publish(REVIEWED_CASE)
    parent = await t.parent()
    w = worker(engine, CountingTools(), InMemorySaver())
    w.host.ports.runs = t.starts
    await drain(w)
    children = await t.children()
    assert {c["status"] for c in children} == {"waiting"}
    with tenant_scope(t.id):
        run = await t.runs.get(parent) or {}
        steps = len(await t.runs.steps(parent))
    assert (run["status"], run["outcome"], run["finished_at"], run["waiting"]) == ("waiting", "done", None, None)
    # A late row for the parent (a decided review's deadline) finds its graph ended and starts nothing again.
    with tenant_scope(t.id):
        await WorkQueue(t.tx, "api", 6.0).enqueue(parent, "timeout", f"late:{parent}")
    await drain(w)
    with tenant_scope(t.id):
        assert len(await t.runs.steps(parent)) == steps
        for child in children[:-1]:
            cancelled, _ = await t.runs.cancel(str(child["id"]))
            await t.runs.settle_parents(cancelled or {})
        assert (await t.runs.get(parent) or {})["status"] == "waiting"
        last, _ = await t.runs.cancel(str(children[-1]["id"]))
        await t.runs.settle_parents(last or {})
        run = await t.runs.get(parent) or {}
    assert run["status"] == "succeeded" and run["finished_at"] is not None


async def test_an_end_marked_failed_fails_the_run_and_names_where_it_ended(
    engine: AsyncEngine,  # noqa: F811
    tenants: Callable[[], Tenant],
) -> None:
    t = tenants()
    lookup = parse(
        {
            "schemaVersion": 2,
            "id": "lookup",
            "name": "Lookup",
            "nodes": [
                {"id": "in", "type": "ops.trigger.request", "typeVersion": 1, "name": "Request"},
                {
                    "id": "failed",
                    "type": "ops.flow.end",
                    "typeVersion": 1,
                    "name": "Lookup failed",
                    "parameters": {"outcome": "tool_failed", "result": "failed"},
                },
            ],
            "connections": [{"from": {"node": "in", "port": "payload"}, "to": {"node": "failed", "port": "in"}}],
        }
    )
    stored = await t.publish(lookup)
    with tenant_scope(t.id):
        run, _ = await start_run(t.runs, stored, team_id=TEAM, mode="live", input={}, run_key=None, created_by="b@x")
    await drain(worker(engine, CountingTools(), InMemorySaver()))
    with tenant_scope(t.id):
        ended = await t.runs.get(str(run["id"])) or {}
    assert (ended["status"], ended["outcome"]) == ("failed", "tool_failed")
    assert ended["error"] == "Ended at Lookup failed, an end marked as a failure" and ended["finished_at"] is not None
