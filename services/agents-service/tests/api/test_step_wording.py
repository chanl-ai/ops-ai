"""Steps worded once, by the API (c-508), by failure mode: an Activity row titled with a tool's name; Activity and the
run page wording the same step differently; Activity reading the directory or the steps once per row; a tool the
catalogue does not know shown by its name."""

from __future__ import annotations

from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event

from ops_agents.activities.catalog import load_catalog
from ops_agents.api import task_view
from ops_agents.api.actors import actors
from ops_agents.api.chat_threads import AssistantBuilder
from ops_agents.api.review_text import describe_call
from ops_agents.store.activity import Activity
from ops_agents.store.cases import CaseStore
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.events import EventLog
from ops_agents.store.tenancy import tenant_scope, tenant_tx
from ops_contracts.chat import ChatMessage, WidgetEvent
from ops_engine.journal import StepRow
from ops_engine.store import RunStore, SqlJournal
from ops_engine.store.tables import engine_definitions
from ops_store.team_scope import acting_as
from tests.api.test_activity import activity
from tests.api.test_case_routes import started_run
from tests.api.test_memory import chat
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.api.test_write_approval_policy import dev_platform, drafted, person  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.conftest import SEED
from tests.engine.test_lifecycle_rights import BUILDER, TENANT
from tests.store.test_cases import store  # noqa: F401  # pyright: ignore[reportUnusedImport]


async def _tool_steps(s: Stack, run: str, calls: list[tuple[str, str, dict[str, Any]]]) -> None:
    """Journal finished tool steps on `run`: (node, operation, input) each."""
    _, rt = s
    journal = SqlJournal(EngineTransactions(rt.db))
    with tenant_scope(TENANT):
        for node, operation, given in calls:
            given_input = {"operation": operation, "input": given}
            key = f"{run}:{node}:1:1"
            row = StepRow(run, node, 1, 1, "running", "read", key, input=given_input, node_type="ops.action.tool")
            await journal.begin(row)


class _Directory:
    """The tool directory with no operations, counting its reads."""

    def __init__(self) -> None:
        self.reads = 0

    async def operations(self) -> list[Any]:
        self.reads += 1
        return []


async def test_activity_never_titles_a_call_with_its_tool_name(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    run = await started_run(c, BUILDER, "wording_check")
    await _tool_steps(stack, run, [("lookup", "get_customer", {"customer_id": "CUS-1002"})])
    thread = await chat(c, BUILDER)
    await EventLog(rt.db).append(
        thread_id=thread, team_id="team_ops", run_id=None, type_="tool_end", node="agent",
        data={"tool": "list_accounts", "status": "ok", "input": {"customerId": "CUS-1002"}},
    )  # fmt: skip
    titles = [r["title"] for r in (await activity(c, BUILDER, kind="tool_call"))["data"]]
    assert titles and not any(t in ("get_customer", "list_accounts", "lookup") or "_" in t for t in titles), titles


async def test_activity_and_the_run_page_say_a_step_alike(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    run = await started_run(c, BUILDER, "wording_alike")
    await _tool_steps(stack, run, [("lookup", "get_customer", {"customer_id": "CUS-1002"})])
    [row] = [r for r in (await activity(c, BUILDER, kind="tool_call"))["data"] if r["ref"]["id"] == run]
    detail = (await c.get(f"/v1/runs/{run}", headers=BUILDER)).json()["data"]
    told = [x["text"] for x in detail["story"]["lines"]]
    assert row["title"] in told, (row["title"], told)


async def test_activity_describes_a_page_of_calls_in_fixed_reads(
    stack: Stack,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, rt = stack
    directory = _Directory()
    monkeypatch.setattr(rt, "directory", lambda: directory)
    statements: list[str] = []

    def count(_c: Any, _cur: Any, statement: str, *_: Any) -> None:
        statements.append(statement)

    async def read_with(n: int) -> int:
        run = await started_run(c, BUILDER, f"wording_reads_{n}")
        await _tool_steps(stack, run, [(f"step{i}", "get_customer", {"customer_id": f"CUS-{i}"}) for i in range(n)])
        statements.clear()
        directory.reads = 0
        event.listen(rt.db.sync_engine, "before_cursor_execute", count)
        try:
            await activity(c, BUILDER, kind="tool_call", pageSize=50)
        finally:
            event.remove(rt.db.sync_engine, "before_cursor_execute", count)
        assert directory.reads == 1, directory.reads
        return len(statements)

    assert await read_with(2) == await read_with(20)


async def test_an_unknown_tool_reads_as_words_everywhere(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    run = await started_run(c, BUILDER, "wording_unknown")
    await _tool_steps(stack, run, [("lookup", "frobnicate_widget", {})])
    [row] = [r for r in (await activity(c, BUILDER, kind="tool_call"))["data"] if r["ref"]["id"] == run]
    assert row["title"] == "Frobnicate widget", row


async def test_the_write_preview_carries_the_operations_labels(stack: Stack) -> None:  # noqa: F811
    """The Human Task page drew a write's input keys made readable in the browser; the region now carries the
    operation's own labels and values, as the one describer words them."""
    _, rt = stack
    call = {"tool": "place_hold", "input": {"accountId": "CHQ-2219", "amount": 2140.55}}
    payload = {"taskType": {"id": "write_approval"}, "params": {"title": "Hold the funds", "call": call}}
    with tenant_scope(TENANT), acting_as("team_ops"):
        task = await task_view.typed_task(rt, payload) or {}
        expected = await describe_call(rt, call, currency=None, money_key=None)
    [preview] = [r["data"] for r in task["regions"] if r["region"] == "write_preview"]
    assert preview["fields"] == expected["fields"] and preview["fields"], preview
    assert preview["sentence"] == expected["sentence"], preview
    assert not any("_" in f["label"] or f["label"] in ("accountId", "amount") for f in preview["fields"]), preview


async def test_a_task_list_reads_the_directory_once(
    dev_platform: AsyncClient,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    james = person("usr_james", ["team_ops"])
    for _ in range(3):
        await drafted(dev_platform, james)
    transport = cast(ASGITransport, dev_platform._transport)  # pyright: ignore[reportPrivateUsage]
    directory = _Directory()
    monkeypatch.setattr(cast(Any, transport.app).state.runtime, "directory", lambda: directory)
    listed = await dev_platform.get("/reviews", headers=james)
    assert listed.status_code == 200 and len(listed.json()["data"]["data"]) >= 3, listed.text
    assert directory.reads == 1, directory.reads


def test_a_chat_widget_names_its_tool_in_words() -> None:
    """A widget's footer printed the tool's name (`lookup_customer`); the widget now carries the action in words."""
    builder = AssistantBuilder(load_catalog(SEED), ChatMessage(id="m1", role="assistant", content="", at="t"))
    view = {"title": "Marcus Bell", "fields": [{"label": "Customer", "value": "CUS-1002"}]}
    looked = {"id": "c1", "tool": "lookup_customer", "status": "ok", "input": {"customerId": "CUS-1002"}, "view": view}
    held = {"tool": "place_hold", "input": {"account_id": "CHQ-2219", "amount": 3250}, "review_id": "r1"}
    events = [*builder.apply("tool_call", looked), *builder.apply("waiting_review", {"id": "i1", "payload": held})]
    widgets = [e.widget for e in events if isinstance(e, WidgetEvent)]
    assert [w.kind for w in widgets] == ["record", "approval"], widgets
    for w in widgets:
        assert w.tool_label and w.tool_label != w.tool and "_" not in w.tool_label, w


async def _opened(store: CaseStore) -> str:  # noqa: F811
    return str((await store.open(team_id="team_ops", subject="Dispute W-1", priority="high", by="run:r1")).case["id"])


async def _responded(store: CaseStore, case_id: str) -> str | None:  # noqa: F811
    return (await store.get(case_id, ["team_ops"]))["responded_at"]


async def test_only_a_person_starts_the_first_response_clock(store: CaseStore) -> None:  # noqa: F811
    case_id = await _opened(store)
    await store.add_event(case_id, "note", ref=None, detail={"text": "auto"}, by="run:r1")
    await store.add_event(case_id, "note", ref=None, detail={"text": "auto"}, by="agent:ag_1")
    await store.change(case_id, {"status": "waiting_on_us"}, by="key:k1")
    assert await _responded(store, case_id) is None
    await store.add_event(case_id, "decision", ref="s1", detail={"decision": "approve"}, by="maya@x.example")
    assert await _responded(store, case_id)


async def test_a_customer_name_change_does_not_start_the_clock(store: CaseStore) -> None:  # noqa: F811
    case_id = await _opened(store)
    await store.change(case_id, {"customer_name": "Marcus Bell", "subject": "Dispute W-2"}, by="maya@x.example")
    assert await _responded(store, case_id) is None
    await store.change(case_id, {"assignee": "maya@x.example"}, by="maya@x.example")
    assert await _responded(store, case_id)


async def test_an_explicit_responded_at_wins(store: CaseStore) -> None:  # noqa: F811
    case_id = await _opened(store)
    imported = "2026-10-01T09:00:00.000Z"
    await store.change(case_id, {"status": "waiting_on_us", "responded_at": imported}, by="maya@x.example")
    await store.add_event(case_id, "note", ref=None, detail={"text": "later"}, by="maya@x.example")
    assert await _responded(store, case_id) == imported


async def test_the_first_response_is_set_once(store: CaseStore) -> None:  # noqa: F811
    case_id = await _opened(store)
    await store.add_event(case_id, "note", ref=None, detail={"text": "first"}, by="maya@x.example")
    first = await _responded(store, case_id)
    await store.change(case_id, {"priority": "urgent"}, by="james@x.example")
    assert first and await _responded(store, case_id) == first


async def test_a_run_outcome_reads_as_words(stack: Stack) -> None:  # noqa: F811
    """The run page printed the outcome's key ("documents_read") in its Run panel and Result section."""
    c, rt = stack
    run = await started_run(c, BUILDER, "wording_outcome")
    with tenant_scope(TENANT):
        await RunStore(EngineTransactions(rt.db)).update(run, status="succeeded", outcome="documents_read")
    detail = (await c.get(f"/v1/runs/{run}", headers=BUILDER)).json()["data"]
    listed = (await c.get("/v1/runs", params={"workflowId": "wording_outcome"}, headers=BUILDER)).json()["data"]
    assert detail["outcome"] == "documents_read" and detail["outcomeText"] == "Documents read", detail
    assert [r["outcomeText"] for r in listed["data"]] == ["Documents read"], listed
    rows = [r for r in (await activity(c, BUILDER, kind="workflow_run"))["data"] if r["ref"]["id"] == run]
    assert [r["outcomeText"] for r in rows] == ["Documents read"], rows


async def test_a_run_actor_without_a_name_is_not_its_id(stack: Stack) -> None:  # noqa: F811
    """A run was named by its workflow's id ("levy_mail_intake_a0877a1d") where people read its name: in the Run panel,
    and as the actor of what it did when its version has no name."""
    c, rt = stack
    run = await started_run(c, BUILDER, "wording_named")
    detail = (await c.get(f"/v1/runs/{run}", headers=BUILDER)).json()["data"]
    assert detail["workflowName"] == "Refund check", detail["workflowName"]
    with tenant_scope(TENANT):
        async with tenant_tx(rt.db) as conn:
            d = engine_definitions
            await conn.execute(d.update().where(d.c.workflow_id == "wording_named").values(name=""))
        named = await actors(rt, [f"run:{run}"])
    assert named[f"run:{run}"]["name"] == "a workflow run", named
    detail = (await c.get(f"/v1/runs/{run}", headers=BUILDER)).json()["data"]
    assert detail["workflowName"] == "a workflow run", detail["workflowName"]


async def test_a_call_of_another_team_is_not_read(stack: Stack) -> None:  # noqa: F811
    """Activity words a chat call by reading its event by id; that read crossed teams, so another team's call input
    could be worded on this team's page."""
    _, rt = stack
    data = {"tool": "list_accounts", "status": "ok", "input": {"customerId": "CUS-9"}}
    with tenant_scope(TENANT):
        theirs = await EventLog(rt.db).append(
            thread_id="th_other", team_id="team_other", run_id=None, type_="tool_end", node="agent", data=data
        )
        rows = [{"kind": "tool_call", "source_type": "chat", "row_id": theirs["id"]}]
        with acting_as("team_ops"):
            seen = await Activity(rt.db).calls(rows)
        with acting_as("team_other"):
            own = await Activity(rt.db).calls(rows)
    assert seen == {} and own[str(theirs["id"])]["tool"] == "list_accounts", (seen, own)


async def test_a_call_carrying_an_object_reads_without_it(stack: Stack) -> None:  # noqa: F811
    """A webhook step's story line read "payload case id case_2379…, customer id CUS-1001, account …": the object the
    call carries flattened into the sentence."""
    _, rt = stack
    payload = {"caseId": "case_2379bac6ca62", "customerId": "CUS-1001", "account": "CHQ-2219", "amount": 2140.55}
    call = {"tool": "notify_webhook", "input": {"hook": "holds", "event": "hold.placed", "payload": payload}}
    with tenant_scope(TENANT):
        told = await describe_call(rt, call, currency=None, money_key=None)
    assert told["sentence"] == "Notify webhook: hook holds, event hold.placed", told
