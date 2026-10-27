"""Open case and Add to case (c-219) through the real worker into the host, on the real database under tenant RLS,
by failure mode: a retried Open case step opens a second case; Add to case joins another team's case; a test run's
case reads as a customer's issue; a later step's note is lost or written twice; a run closes a case (c-532)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.api.engine_cases import RunCases
from ops_agents.store.cases import CaseStore
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.ports import CaseNotFoundError
from tests.engine.test_start_workflow import TEAM, Tenant, tenants  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_worker import (  # noqa: F401
    CountingTools,  # pyright: ignore[reportUnusedImport]
    drain,  # pyright: ignore[reportUnusedImport]
    engine,  # pyright: ignore[reportUnusedImport]
    worker,  # pyright: ignore[reportUnusedImport]
)

OTHER = "team_b"


def dispute(case_id: str = "$.nodes.open.out.caseId", **extra: Any) -> Any:
    return parse(
        {
            "schemaVersion": 2,
            "id": "dispute",
            "name": "Dispute",
            "nodes": [
                {"id": "in", "type": "ops.trigger.request", "typeVersion": 1, "name": "Request"},
                {
                    "id": "open",
                    "type": "ops.action.openCase",
                    "typeVersion": 1,
                    "name": "Open case",
                    "parameters": {"subject": "$.input.subject", "priority": "high", "customerId": "$.input.customer"}
                    | extra.get("open", {}),
                },
                {
                    "id": "join",
                    "type": "ops.action.addToCase",
                    "typeVersion": 1,
                    "name": "Add to case",
                    "parameters": {"caseId": case_id, "note": "Statement requested"} | extra.get("join", {}),
                },
                {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {}},
                {
                    "id": "failed",
                    "type": "ops.flow.end",
                    "typeVersion": 1,
                    "name": "Failed",
                    "parameters": {"outcome": "no case"},
                },
            ],
            "connections": [
                {"from": {"node": "in", "port": "payload"}, "to": {"node": "open", "port": "in"}},
                {"from": {"node": "open", "port": "opened"}, "to": {"node": "join", "port": "in"}},
                {"from": {"node": "open", "port": "error"}, "to": {"node": "failed", "port": "in"}},
                {"from": {"node": "join", "port": "added"}, "to": {"node": "done", "port": "in"}},
                {"from": {"node": "join", "port": "error"}, "to": {"node": "failed", "port": "in"}},
            ],
        }
    )


class Cases:
    def __init__(self, t: Tenant, db: AsyncEngine) -> None:
        self.t, self.store = t, CaseStore(db)
        self.port = RunCases(t.runs, self.store)

    async def run(self, d: Any, *, mode: str = "live", db: AsyncEngine) -> str:
        from ops_agents.api.engine_runs import start_run  # noqa: PLC0415 - the module the fixture shares

        stored = await self.t.publish(d)
        with tenant_scope(self.t.id):
            run, _ = await start_run(
                self.t.runs,
                stored,
                team_id=TEAM,
                mode=mode,  # pyright: ignore[reportArgumentType]
                input={"subject": "Card dispute", "customer": "C-1001"},
                run_key=None,
                created_by="b@x",
            )
        w = worker(db, CountingTools(), InMemorySaver())
        w.host.ports.cases = self.port
        await drain(w)
        return str(run["id"])

    async def all(self, team: str = TEAM) -> list[dict[str, Any]]:
        with tenant_scope(self.t.id):
            rows, _ = await self.store.list([team])
            return rows


@pytest.fixture
async def cases(engine: AsyncEngine, tenants: Callable[[], Tenant]) -> AsyncIterator[Cases]:  # noqa: F811
    yield Cases(tenants(), engine)


async def test_a_run_opens_one_case_and_joins_it_and_a_retry_opens_no_second(
    cases: Cases,
    engine: AsyncEngine,  # noqa: F811
) -> None:
    run_id = await cases.run(dispute(), db=engine)
    [case] = await cases.all()
    assert (case["subject"], case["priority"], case["customer_id"], case["created_by"]) == (
        "Card dispute",
        "high",
        "C-1001",
        f"run:{run_id}",
    )
    with tenant_scope(cases.t.id):
        assert (await cases.t.runs.get(run_id) or {})["status"] == "succeeded"
        events = await cases.store.events(str(case["id"]))
        again = await cases.port.open(run_id, {"subject": "Card dispute"}, f"{run_id}:open:1")
        await cases.port.add(run_id, str(case["id"]), "Statement requested", key=f"{run_id}:join:1")
        after = await cases.store.events(str(case["id"]))
    assert [(e["kind"], e["ref"]) for e in events] == [("opened", None), ("run", run_id), ("note", f"{run_id}:join:1")]
    assert events[-1]["detail"] == {"text": "Statement requested"}, "the join step's note is on the timeline"
    assert (again.case_id, again.created) == (case["id"], False), "the step's key finds the case it opened"
    assert len(after) == len(events) and len(await cases.all()) == 1, "a retried step adds nothing"


async def test_add_to_case_never_joins_another_teams_case(cases: Cases, engine: AsyncEngine) -> None:  # noqa: F811
    with tenant_scope(cases.t.id):
        theirs = await cases.store.open(team_id=OTHER, subject="Fraud alert", priority="urgent", by="x@b")
    run_id = await cases.run(dispute(str(theirs.case["id"])), db=engine)
    with tenant_scope(cases.t.id):
        run = await cases.t.runs.get(run_id) or {}
        assert (run["status"], run["outcome"]) == ("succeeded", "no case"), "the step took its error port"
        assert [e["kind"] for e in await cases.store.events(str(theirs.case["id"]))] == ["opened"]
        with pytest.raises(CaseNotFoundError):
            await cases.port.add(run_id, str(theirs.case["id"]), None)


async def test_a_test_runs_case_says_it_is_a_test(cases: Cases, engine: AsyncEngine) -> None:  # noqa: F811
    await cases.run(dispute(), mode="test", db=engine)
    [case] = await cases.all()
    assert case["subject"] == "[Test] Card dispute"


async def test_a_case_keeps_the_fields_a_run_gives_it_and_a_later_step_adds_more(
    cases: Cases,
    engine: AsyncEngine,  # noqa: F811
) -> None:
    opened = {"fields": {"customer": "$.input.customer", "amount": 120.5}}
    joined = {"fields": {"statement": "requested", "amount": 99}}
    await cases.run(dispute(open=opened, join=joined), db=engine)
    [case] = await cases.all()
    assert case["fields"] == {"customer": "C-1001", "amount": 99, "statement": "requested"}, case["fields"]


async def test_a_run_resolves_its_case_and_never_closes_one(cases: Cases, engine: AsyncEngine) -> None:  # noqa: F811
    run_id = await cases.run(dispute(join={"status": "resolved", "note": "Replied: no account at the bank"}), db=engine)
    [case] = await cases.all()
    with tenant_scope(cases.t.id):
        events = await cases.store.events(str(case["id"]))
        with pytest.raises(ValueError, match="closing is a person's"):
            await cases.port.add(run_id, str(case["id"]), None, status="closed")
        [after] = await cases.all()
    assert case["status"] == "resolved", case["status"]
    assert ("field", f"run:{run_id}") in [(e["kind"], e["by"]) for e in events], "the move is on the timeline"
    assert after["status"] == "resolved"


async def test_an_open_case_step_pins_its_case_types_published_version_and_an_unknown_type_is_its_error_port(
    cases: Cases,
    engine: AsyncEngine,  # noqa: F811
) -> None:
    """c-291: a case keeps the case type version it opened with, so editing the type later changes no open case."""
    await cases.run(dispute(open={"caseType": "complaint"}), db=engine)
    [case] = await cases.all()
    assert (case["type_id"], case["type_version"]) == ("complaint", 1), case
    unknown = await cases.run(dispute(open={"caseType": "no_such_type"}), db=engine)
    with tenant_scope(cases.t.id):
        run = await cases.t.runs.get(unknown) or {}
        [step] = [s for s in await cases.t.runs.steps(unknown) if s["node_id"] == "open"]
    assert (run["outcome"], step["port"], step["output"]["code"]) == ("no case", "error", "case_type_unknown"), step
