"""Redrive of a Failed run through the worker on PostgreSQL, by failure mode: a redrive runs again a step that
completed or sends again a write that ran, and a redrive runs the workflow's latest version instead of the run's."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.ports import Access, ToolResult
from ops_engine.store import DefinitionStore, RunStore
from ops_engine.store.tables import engine_steps
from ops_service_kit.ids import new_id
from tests.engine.test_worker import (
    BASIC,
    CountingTools,
    UncertainTools,
    drain,
    engine,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    start,
    worker,
)
from tests.run_rows import write_run


class AnsweredTools(UncertainTools):
    """The write timed out at the caller but ran at the system: the gateway's record under its key says done."""

    async def find(self, key: str, operation: str) -> ToolResult | None:
        return ToolResult(True, {"id": "C-1"}) if key in self.calls else None


async def failed_run(db: AsyncEngine, tenant: str, tools: UncertainTools) -> str:
    run_id = await start(db, tenant, {"customerId": "C-1", "amount": 250})
    await drain(worker(db, tools, InMemorySaver()))
    with tenant_scope(tenant):
        run = await RunStore(EngineTransactions(db)).get(run_id) or {}
    assert run["status"] == "failed", run
    return run_id


async def test_a_redrive_reruns_no_completed_step_and_sends_no_write_twice(engine: AsyncEngine) -> None:  # noqa: F811
    tenant, tools = f"t-{uuid4().hex[:8]}", AnsweredTools()
    run_id = await failed_run(engine, tenant, tools)
    runs = RunStore(EngineTransactions(engine))
    with tenant_scope(tenant):
        _, changed = await runs.redrive(run_id)
    assert changed
    await drain(worker(engine, tools, InMemorySaver()))
    with tenant_scope(tenant):
        run = await runs.get(run_id) or {}
        steps = await runs.steps(run_id)
    waiting: dict[str, Any] = run["waiting"] or {}
    assert (run["status"], waiting.get("node")) == ("waiting", "review"), run
    assert [s["attempt"] for s in steps if s["node_id"] == "fields"] == [1], "a completed step ran again"
    assert [k for k in tools.calls if k.startswith(run_id)] == [f"{run_id}:lookup:1:1"], "the write was sent again"


class UnsetTools(CountingTools):
    """A read the gateway refuses with a definite answer until the builder sets the app's address (`fixed`); then the
    system is out for the first `outages` calls, and answers after."""

    fixed = False
    outages = 0
    outage = "UPSTREAM_TIMEOUT"

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        if self.fixed and self.outages == 0:
            return await super().call(operation, input, key, generation, token)
        self.calls.append(key)
        if self.fixed:
            self.outages -= 1
            error = {"code": self.outage, "message": "crm.test did not answer", "side": "upstream"}
            return ToolResult(False, {"error": error}, reason="the operation returned an error")
        error = {"code": "CONNECTION_NOT_SET", "message": "This tool's app names no address for this environment."}
        return ToolResult(False, {"error": error}, reason="This tool's app names no address for this environment.")


async def failed_at_its_end(db: AsyncEngine, tenant: str, tools: CountingTools, *, on_timeout: bool = False) -> str:
    """A run of BASIC with its Failed End marked as a failure, as a builder's is: the lookup leaves by its error port
    and the run fails there."""
    wire: dict[str, Any] = BASIC.wire()
    for n in wire["nodes"]:
        if n["id"] == "failed":
            n["parameters"] = {**n["parameters"], "result": "failed"}
        if on_timeout and n["id"] == "lookup":
            n["parameters"] = {**n["parameters"], "onTimeout": "port"}
    if on_timeout:
        timed_out = {"from": {"node": "lookup", "port": "timeout"}, "to": {"node": "failed", "port": "in"}}
        wire["connections"].append(timed_out)
    failing = parse(wire)
    tx = EngineTransactions(db)
    with tenant_scope(tenant):
        version, _ = await DefinitionStore(tx).publish(
            failing.id, name="Refund", definition=wire, digest=failing.digest(), now="now", by="a@x", stage="live"
        )
        run_id = new_id("wfrun")
        row = {"id": run_id, "team_id": "team_a", "workflow_id": failing.id, "version": version}
        row |= {"digest": failing.digest(), "run_key": run_id, "mode": "live", "created_by": "a@x"}
        await write_run(tx, row | {"input": {"customerId": "C-1", "amount": 250}})
    await drain(worker(db, tools, InMemorySaver()))
    with tenant_scope(tenant):
        assert ((await RunStore(tx).get(run_id)) or {})["status"] == "failed"
    return run_id


async def redriven(db: AsyncEngine, tenant: str, run_id: str, tools: CountingTools) -> tuple[dict[str, Any], list[Any]]:
    runs = RunStore(EngineTransactions(db))
    with tenant_scope(tenant):
        _, changed = await runs.redrive(run_id)
    assert changed
    await drain(worker(db, tools, InMemorySaver()))
    with tenant_scope(tenant):
        return (await runs.get(run_id) or {}), await runs.steps(run_id)


async def test_a_redrive_runs_the_step_that_left_by_its_error_port_again(engine: AsyncEngine) -> None:  # noqa: F811
    # Once the cause is fixed, a redrive runs the lookup again under its next attempt's key; it does not return the
    # recorded error and end at the same End.
    tenant, tools = f"t-{uuid4().hex[:8]}", UnsetTools()
    run_id = await failed_at_its_end(engine, tenant, tools)
    tools.fixed = True
    run, steps = await redriven(engine, tenant, run_id, tools)
    assert [(s["attempt"], s["status"]) for s in steps if s["node_id"] == "lookup"] == [(1, "redriven"), (2, "ok")]
    assert [k for k in tools.calls if k.startswith(run_id)] == [f"{run_id}:lookup:1:1", f"{run_id}:lookup:1:2"]
    assert [s["attempt"] for s in steps if s["node_id"] == "fields"] == [1], "a completed step ran again"
    waiting: dict[str, Any] = run["waiting"] or {}
    assert (run["status"], waiting.get("node")) == ("waiting", "review"), run


async def test_a_redriven_step_keeps_its_own_retries_however_old_the_failure(
    engine: AsyncEngine,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A step's total duration counts from its earliest attempt; the set-aside one failed a day ago, so counted from it
    # the redriven step would have no time left for a second try (and a one-second limit on its first).
    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr("ops_engine.compiler.sleep", no_wait)
    tenant, tools = f"t-{uuid4().hex[:8]}", UnsetTools()
    run_id = await failed_at_its_end(engine, tenant, tools)
    async with engine.begin() as c:
        await c.execute(
            engine_steps.update().where(engine_steps.c.run_id == run_id).values(started_at="2026-11-01T00:00:00Z")
        )
    tools.fixed, tools.outages = True, 1
    run, steps = await redriven(engine, tenant, run_id, tools)
    lookup = [(s["attempt"], s["status"]) for s in steps if s["node_id"] == "lookup"]
    assert lookup == [(1, "redriven"), (2, "error"), (3, "ok")], lookup
    assert run["status"] == "waiting", run


class UnsetWrites(UnsetTools):
    """UnsetTools as a write, whose outages never reach the system."""

    outage = "CONNECT_FAILED"

    async def access(self, operation: str) -> Access:
        return "write"


async def test_a_redriven_write_keeps_its_own_attempts_and_its_reason_counts_only_them(
    engine: AsyncEngine,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The set-aside attempt is not one of the redriven write's three: two outages that never reached the system are
    # sent again, and the third try answers.
    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr("ops_engine.compiler.sleep", no_wait)
    tenant, tools = f"t-{uuid4().hex[:8]}", UnsetWrites()
    run_id = await failed_at_its_end(engine, tenant, tools)
    # Redriven before the cause is fixed, it fails again on one try; the reason does not count the set-aside one.
    run, _ = await redriven(engine, tenant, run_id, tools)
    assert run["status"] == "failed" and "attempts" not in str(run["error"]), run["error"]
    tools.fixed, tools.outages = True, 2
    run, steps = await redriven(engine, tenant, run_id, tools)
    lookup = [(s["attempt"], s["status"]) for s in steps if s["node_id"] == "lookup"]
    assert lookup == [(1, "redriven"), (2, "redriven"), (3, "error"), (4, "error"), (5, "ok")], lookup
    assert run["status"] == "waiting", run


async def test_a_redrive_never_resends_a_write_that_left_by_its_timeout_port(engine: AsyncEngine) -> None:  # noqa: F811
    # A write the system did not answer in time may have run; the gateway's record under its key decides, here done.
    tenant, tools = f"t-{uuid4().hex[:8]}", AnsweredTools()
    run_id = await failed_at_its_end(engine, tenant, tools, on_timeout=True)
    run, steps = await redriven(engine, tenant, run_id, tools)
    assert [k for k in tools.calls if k.startswith(run_id)] == [f"{run_id}:lookup:1:1"], "the write was sent again"
    assert run["status"] == "waiting", (run, [(s["attempt"], s["status"], s["port"]) for s in steps])


class MayHaveRunTools(CountingTools):
    """A write whose call reached the system and then failed in a way that does not say whether it acted, recorded
    under `code`; the gateway's record under its key says it was done."""

    def __init__(self, code: str) -> None:
        super().__init__()
        self.code = code

    async def access(self, operation: str) -> Access:
        return "write"

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        self.calls.append(key)
        error = {"code": self.code, "message": f"ConnectionResetError calling {operation}"}
        return ToolResult(False, {"error": error}, reason="the operation returned an error")

    async def find(self, key: str, operation: str) -> ToolResult | None:
        return ToolResult(True, {"id": "C-1"}) if key in self.calls else None


@pytest.mark.parametrize("code", ["UPSTREAM_UNREACHABLE", "PLUGIN_FAILED", "ANSWER_UNREADABLE"])
async def test_a_redrive_never_resends_a_write_whose_error_says_it_may_have_run(
    engine: AsyncEngine,  # noqa: F811
    code: str,
) -> None:
    # A plugin's request that broke off, a plugin that raised after sending, an answer that could not be read: the
    # write may have run, so a redrive reads the gateway's record under its key (here done) instead of sending it.
    tenant, tools = f"t-{uuid4().hex[:8]}", MayHaveRunTools(code)
    run_id = await failed_at_its_end(engine, tenant, tools)
    run, steps = await redriven(engine, tenant, run_id, tools)
    assert [k for k in tools.calls if k.startswith(run_id)] == [f"{run_id}:lookup:1:1"], "the write was sent again"
    assert run["status"] == "waiting", (run, [(s["attempt"], s["status"], s["port"]) for s in steps])


async def test_a_redrive_runs_the_version_the_run_pinned_not_the_latest(engine: AsyncEngine) -> None:  # noqa: F811
    tenant, tools = f"t-{uuid4().hex[:8]}", AnsweredTools()
    run_id = await failed_run(engine, tenant, tools)
    # A later publish sends the lookup straight to an End: a run on it would succeed instead of waiting for review.
    later: dict[str, Any] = BASIC.wire()
    later["connections"] = [
        c if c["from"] != {"node": "lookup", "port": "ok"} else {**c, "to": {"node": "approved", "port": "in"}}
        for c in later["connections"]
    ]
    newer = parse(later)
    tx = EngineTransactions(engine)
    with tenant_scope(tenant):
        version, _ = await DefinitionStore(tx).publish(
            newer.id, name="Refund", definition=newer.wire(), digest=newer.digest(), now="now", by="a@x", stage="live"
        )
        assert version == 2
        await RunStore(tx).redrive(run_id)
    await drain(worker(engine, tools, InMemorySaver()))
    with tenant_scope(tenant):
        run = await RunStore(tx).get(run_id) or {}
    assert (run["status"], run["version"]) == ("waiting", 1), run
