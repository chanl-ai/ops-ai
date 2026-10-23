"""The run told for people (c-477), on PostgreSQL through the run detail route, by failure mode: an email run shows
JSON instead of its email, or a run that is not an email shows one; a read differs from what Human Tasks shows; a
child row has no name, the wrong state, another child's case or task, or another team's case; another team's run is
told; a workflow-scoped key reads another workflow's names; the read grows a query per child; past the cap the rest
disappear silently."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api import engine_reviews, review_text, run_story
from ops_agents.api.routers.engine import get_engine_run
from ops_agents.store.cases import CaseStore
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.review_assignments import ReviewAssignments
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.store import DefinitionStore, RunStore
from ops_engine.store.tables import engine_steps
from ops_service_kit.ids import new_id
from tests.engine.test_run_reads_masked import Policies
from tests.engine.test_worker import M

INTAKE = parse(
    {
        "schemaVersion": 2,
        "id": "intake",
        "nodes": [
            {"id": "mail", "type": "ops.trigger.email", "typeVersion": 1, "parameters": {}},
            {"id": "read", "type": "ops.ai.extract", "typeVersion": 1, "name": "Read the debtors", "parameters": {}},
            {"id": "each", "type": "ops.action.workflow", "typeVersion": 1, "name": "A run per debtor",
             "parameters": {"workflow": "debtor"}},
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Read", "parameters": {"outcome": "read"}},
        ],
        "connections": [],
    }
)  # fmt: skip
DEBTOR = parse(
    {
        "schemaVersion": 2,
        "id": "debtor",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            {"id": "case", "type": "ops.action.openCase", "typeVersion": 1, "parameters": {"subject": "x"}},
            {"id": "find", "type": "ops.flow.humanReview", "typeVersion": 1, "name": "Find the customer",
             "parameters": {"options": [{"name": "found", "label": "Customer found"}, {"name": "not_ours"}]}},
            {"id": "held", "type": "ops.flow.end", "typeVersion": 1, "name": "Held", "parameters": {"outcome": "held"}},
        ],
        "connections": [],
    }
)  # fmt: skip
NOTICE = "fil_0123456789abcdef0123456789abcdef"
EMAIL = {
    "messageId": "m1",
    "from": "registry@court.example",
    "subject": "Notice of garnishment",
    "body": "Please find the notice attached.",
    "receivedAt": "2026-10-21T09:00:00Z",
    "mailbox": "legal@bank.test",
    "folder": "inbox",
    "attachments": [{"fileId": NOTICE, "name": "notice.pdf", "mime": "application/pdf", "size": 2152}],
    "bodyFile": {"fileId": "fil_body000000000", "name": "email-body.txt", "mime": "text/plain", "size": 30},
    "skipped": [{"name": "huge.zip", "reason": "too_large", "message": "The file is larger than 25 MB."}],
}
FIELD = {
    "value": "Marcus Bell",
    "extractedValue": "Marcus Bell",
    "confidence": 0.97,
    "needsReview": False,
    "citation": {"page": 1, "quote": "Debtor 1: Marcus Bell"},
    "boxes": [{"page": 1, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.02}],
}
READ = {
    "extractionId": "ext_1",
    "fileId": NOTICE,
    "floor": 0.8,
    "schema": [{"key": "name", "label": "Name", "type": "text", "required": True}],
    "records": [{"values": {"name": "Marcus Bell"}, "fields": {"name": FIELD}}],
}


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


class World:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine, self.tenant = engine, f"t-{uuid4().hex[:8]}"
        self.tx = EngineTransactions(engine)
        self.versions: dict[str, int] = {}

    async def publish(self, flow: Any) -> None:
        with tenant_scope(self.tenant):
            version, _ = await DefinitionStore(self.tx).publish(
                flow.id, name=flow.id.title(), definition=flow.wire(), digest=flow.digest(), now="n", by="a@x",
                stage="live",
            )  # fmt: skip
        self.versions[flow.id] = version

    async def run(self, flow: Any, given: Any, *, team: str = "team_ops", created_by: str = "a@x", **after: Any) -> str:
        run_id = new_id("wfrun")
        with tenant_scope(self.tenant):
            store = RunStore(self.tx)
            row = {"id": run_id, "team_id": team, "workflow_id": flow.id, "version": self.versions[flow.id]}
            await store.create(row | {"digest": flow.digest(), "run_key": run_id, "mode": "live", "input": given,
                                      "created_by": created_by})  # fmt: skip
            if after:
                await store.update(run_id, **after)
        return run_id

    async def step(self, run_id: str, node: str, port: str, output: Any, iteration: int = 1) -> None:
        with tenant_scope(self.tenant):
            async with self.tx.tenant_tx() as c:
                await c.execute(
                    engine_steps.insert().values(
                        run_id=run_id, node_id=node, iteration=iteration, attempt=1, tenant_id=self.tenant,
                        status="ok", effects="none", key=f"{run_id}:{node}:{iteration}:1", port=port,
                        started_at="2026-10-21T09:00:00Z", finished_at="2026-10-21T09:00:01Z", output=output,
                    )
                )  # fmt: skip

    async def case(self, run_id: str, *, team: str = "team_ops", **given: Any) -> str:
        with tenant_scope(self.tenant):
            store = CaseStore(self.engine)
            opened = await store.open(team_id=team, priority="high", by="a@x", **given)
            case_id = str(opened.case["id"])
            await store.add_event(case_id, "run", ref=run_id, detail={}, by="a@x")
        return case_id

    async def read(self, run_id: str, mask: Any = None) -> dict[str, Any]:
        rt: Any = SimpleNamespace(
            db=self.engine, policies=Policies({"team_ops": False} if mask is None else mask),
            settings=SimpleNamespace(review_sla_hours=24.0),
        )  # fmt: skip
        with tenant_scope(self.tenant):
            return json.loads(bytes((await get_engine_run(rt, M, run_id)).body))["data"]


async def _notice(w: World, debtors: int = 2, ssn: str | None = None) -> tuple[str, list[str]]:
    """An email run that read the notice and started a run per debtor: Marcus held after Maya found him, Jordan
    waiting on Find the customer, assigned to Maya; then a run of another team that its step also names."""
    for flow in (INTAKE, DEBTOR):
        await w.publish(flow)
    marcus = await w.run(DEBTOR, {"record": {"name": "Marcus Bell"}}, status="succeeded", outcome="held")
    await w.step(marcus, "find", "found", {"decision": "found", "by": "maya@x", "reason": "same address"})
    await w.step(marcus, "held", "", {"outcome": "held"})
    await w.case(marcus, subject="Levy notice: Marcus Bell", customer_name="Marcus Bell",
                 fields={"accounts": [{"id": "CHQ-2219", "balance": 5000}]})  # fmt: skip
    waiting = {"node": "find", "iteration": 1, "interruptId": "i1", "payload": {"title": "Find the customer"}}
    jordan = await w.run(DEBTOR, {"record": {"name": "Jordan Whitfield"}}, status="waiting", waiting=waiting)
    await w.case(jordan, team="team_other", subject="No customer matched: Jordan Whitfield")
    with tenant_scope(w.tenant):
        await ReviewAssignments(w.engine).assign(f"{jordan}:find:1", "maya@x", by="a@x")
    theirs = await w.run(DEBTOR, {"record": {"name": "Someone Else"}}, team="team_other")
    kids = [marcus, jordan][:debtors]
    parent = await w.run(INTAKE, EMAIL, status="succeeded", outcome="read")
    read = READ
    if ssn:
        record = {
            "values": {"name": "Marcus Bell", "ssn": ssn},
            "fields": {"name": FIELD, "ssn": FIELD | {"value": ssn}},
        }
        read = READ | {"records": [record]}
    await w.step(parent, "read", "ok", read)
    runs = [{"index": i, "runId": r, "created": True, "label": n} for i, (r, n) in
            enumerate(zip(kids, ["Marcus Bell", "Jordan Whitfield"], strict=False))]  # fmt: skip
    runs.append({"index": len(runs), "runId": theirs, "created": True, "label": "Someone Else"})
    await w.step(parent, "each", "started", {"workflowId": "debtor", "count": len(runs), "runs": runs})
    return parent, kids


async def test_an_email_run_tells_its_email(engine: AsyncEngine) -> None:
    w = World(engine)
    parent, _ = await _notice(w)
    email = (await w.read(parent))["story"]["email"]
    assert email["from"] == "registry@court.example" and email["body"] == "Please find the notice attached."
    assert email["attachments"] == [{"fileId": NOTICE, "name": "notice.pdf", "type": "application/pdf", "size": 2152}]
    assert email["skipped"] == [{"name": "huge.zip", "message": "The file is larger than 25 MB."}]
    assert email["bodyFile"] == {"fileId": "fil_body000000000", "name": "email-body.txt"}


async def test_a_request_run_has_no_email_even_when_its_input_looks_like_one(engine: AsyncEngine) -> None:
    w = World(engine)
    await w.publish(DEBTOR)
    run = await w.run(DEBTOR, EMAIL)
    assert (await w.read(run))["story"]["email"] is None


async def test_a_read_step_is_told_as_human_tasks_tells_it(engine: AsyncEngine) -> None:
    w = World(engine)
    parent, _ = await _notice(w)
    [told] = (await w.read(parent))["story"]["reads"]
    shown = engine_reviews.document_read({"read": READ, "document": "notice.pdf"}, {}, None)
    assert told["name"] == "Read the debtors" and told["read"] == shown
    assert told["read"]["records"][0]["fields"]["name"]["boxes"] == FIELD["boxes"]


async def test_each_child_is_named_with_where_it_is_its_case_and_its_task(engine: AsyncEngine) -> None:
    w = World(engine)
    parent, (marcus, jordan) = await _notice(w)
    story = (await w.read(parent))["story"]
    rows = {c["runId"]: c for c in story["children"]}
    assert [c["label"] for c in story["children"]] == ["Marcus Bell", "Jordan Whitfield"]
    held, waits = rows[marcus], rows[jordan]
    assert (held["state"], held["ending"]) == ("Held", "Held")
    assert held["cases"][0]["customer"] == "Marcus Bell"
    assert held["cases"][0]["facts"] == [{"label": "Accounts", "value": "CHQ-2219"}]
    assert held["tasks"] == [
        {"reviewId": f"{marcus}:find:1", "title": "Find the customer", "open": False, "decision": "Customer found",
         "state": "Find the customer: Customer found by maya@x"}
    ]  # fmt: skip
    assert waits["state"] == "Waiting for a person"
    assert waits["tasks"] == [
        {"reviewId": f"{jordan}:find:1", "title": "Find the customer", "open": True, "decision": None,
         "state": "Find the customer · waiting for maya@x"}
    ]  # fmt: skip


async def test_another_teams_child_and_case_are_not_told(engine: AsyncEngine) -> None:
    w = World(engine)
    parent, (_, jordan) = await _notice(w)
    story = (await w.read(parent))["story"]
    assert "Someone Else" not in json.dumps(story)
    assert next(c for c in story["children"] if c["runId"] == jordan)["cases"] == []


async def test_a_scoped_key_sees_other_workflows_children_by_status_only(engine: AsyncEngine) -> None:
    w = World(engine)
    parent, _ = await _notice(w)
    rt: Any = SimpleNamespace(db=engine)
    with tenant_scope(w.tenant):
        run = await RunStore(w.tx).get(parent)
        steps = run_story.steps_view(await RunStore(w.tx).steps(parent))
        story = await run_story.story(rt, run or {}, steps, scope=("workflow", "intake"), masking=False)
    assert [(c["label"], c["cases"], c["tasks"]) for c in story["children"]] == [("Debtor", [], [])] * 2


async def test_the_story_reads_no_more_for_two_children_than_for_one(engine: AsyncEngine) -> None:
    counts: list[int] = []
    for debtors in (1, 2):
        w = World(engine)
        parent, _ = await _notice(w, debtors)
        seen: list[str] = []

        def record(_c: Any, _cur: Any, statement: str, *_: Any, into: list[str] = seen) -> None:
            into.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", record)
        await w.read(parent)
        event.remove(engine.sync_engine, "before_cursor_execute", record)
        counts.append(sum(s.lstrip().upper().startswith("SELECT") for s in seen))
    assert counts[0] == counts[1], counts


async def test_with_masking_on_channel_addresses_show_and_what_was_read_is_masked(engine: AsyncEngine) -> None:
    """c-477 staging: the sender and mailbox read "[email]". They are where the email came from, not a customer's
    data, so they show on the email and in the input; what a document says (an SSN here) stays masked."""
    w = World(engine)
    parent, (marcus, _) = await _notice(w, ssn="123-45-6789")
    shown = await w.read(parent, mask={})
    story = shown["story"]
    assert story["email"]["from"] == "registry@court.example" and story["email"]["mailbox"] == "legal@bank.test"
    assert shown["input"]["from"] == "registry@court.example" and shown["input"]["mailbox"] == "legal@bank.test"
    assert "123-45-6789" not in json.dumps(shown)
    assert story["children"][0]["runId"] == marcus and story["email"]["attachments"][0]["fileId"] == NOTICE


async def test_a_child_run_shows_the_address_its_email_run_was_sent_from(engine: AsyncEngine) -> None:
    w = World(engine)
    await w.publish(INTAKE)
    await w.publish(DEBTOR)
    parent = await w.run(INTAKE, EMAIL)
    child = await w.run(DEBTOR, {"from": "registry@court.example", "note": "write to ann.lee@example.com"},
                        created_by=f"run:{parent}")  # fmt: skip
    shown = await w.read(child, mask={})
    assert shown["input"]["from"] == "registry@court.example" and "ann.lee@example.com" not in json.dumps(shown)


async def test_a_read_names_the_file_as_it_arrived(engine: AsyncEngine) -> None:
    """c-477 staging: files-service keeps one file per bytes, so a notice sent again kept the first upload's name
    (levy-2b2c3df7.pdf); the run names it as its input does."""
    w = World(engine)
    parent, _ = await _notice(w)
    [told] = (await w.read(parent))["story"]["reads"]
    assert told["read"]["fileName"] == "notice.pdf"


async def test_an_email_with_no_attachments_and_a_step_that_started_none_say_so(engine: AsyncEngine) -> None:
    w = World(engine)
    await w.publish(INTAKE)
    parent = await w.run(INTAKE, EMAIL | {"attachments": [], "skipped": []}, status="waiting",
                         waiting={"node": "check", "iteration": 1, "interruptId": "i", "payload": {}})  # fmt: skip
    await w.step(parent, "read", "review", READ | {"records": []})
    await w.step(parent, "each", "started", {"workflowId": "debtor", "count": 0, "runs": []})
    story = (await w.read(parent))["story"]
    assert story["email"]["attachments"] == [] and story["children"] == [] and story["childrenMore"] == 0
    assert story["reads"][0]["read"]["records"] == []


def test_past_the_cap_the_rest_are_counted() -> None:
    nodes = {"each": {"id": "each", "type": "ops.action.workflow", "typeVersion": 1}}
    runs = [{"index": i, "runId": f"wfrun_{i:012d}"} for i in range(run_story.MAX_CHILDREN + 3)]
    step = {"nodeId": "each", "status": "ok", "port": "started", "output": {"runs": runs}}
    told, more = run_story.started_entries([step], nodes)
    assert len(told) == run_story.MAX_CHILDREN and more == 3


async def test_a_run_tells_what_it_did_in_sentences_oldest_first(engine: AsyncEngine) -> None:
    w = World(engine)
    parent, (marcus, _) = await _notice(w)
    told = [x["text"] for x in (await w.read(parent))["story"]["lines"]]
    # Another team's run the step started is neither named nor counted. The steps finished at the same instant here,
    # so after the email their order is the journal's.
    assert told[0] == "Email from registry@court.example: Notice of garnishment", told
    assert sorted(told[1:]) == [
        "Read notice.pdf: 1 record, 1 field",
        "Started 2 runs of Debtor: Marcus Bell, Jordan Whitfield",
    ], told
    lines = (await w.read(marcus))["story"]["lines"]
    assert [x["text"] for x in lines] == [
        "a@x started Debtor",
        "Asked team_ops: Find the customer",
        "maya@x chose Customer found: Find the customer",
        "Debtor finished: Held",
    ], lines
    decided = lines[2]
    assert (decided["source"], decided["actor"], decided["href"]) == ("person", "maya@x", f"/reviews/{marcus}:find:1")


def _no_entry(_name: str) -> None:
    return None


class _Directory:
    def __init__(self) -> None:
        self.reads = 0

    async def operations(self) -> list[Any]:
        self.reads += 1
        return []


def _tool_step(node: str, iteration: int, operation: str, given: dict[str, Any]) -> dict[str, Any]:
    at = "2026-10-21T09:00:01Z"
    return {"nodeId": node, "iteration": iteration, "status": "ok", "port": "ok", "output": {},
            "input": {"operation": operation, "input": given},
            "attempts": [{"startedAt": at, "finishedAt": at}]}  # fmt: skip


async def test_a_tool_without_a_catalogue_entry_reads_as_words_and_the_directory_is_read_once() -> None:
    directory = _Directory()
    rt: Any = SimpleNamespace(directory=lambda: directory, catalog=SimpleNamespace(tool=_no_entry))
    nodes = {"hold": {"id": "hold", "type": "ops.action.tool", "typeVersion": 1, "name": "Hold the funds"}}
    steps = [_tool_step("hold", i, "place_hold", {"accountId": "CHQ-2219", "amount": 2140.55}) for i in (1, 2, 3)]
    calls = await review_text.describe_calls(rt, run_story.tool_calls(steps, nodes))
    run: dict[str, Any] = {"id": "wfrun_x", "created_by": "a@x", "created_at": "2026-10-21T09:00:00Z", "input": {}}
    told = run_story.lines(run, steps, nodes, workflow="Holds", team="Operations", calls=calls, who={})
    assert [x["text"] for x in told[1:]] == ["Place hold: account id CHQ-2219, amount 2,140.55"] * 3, told
    assert directory.reads == 1, directory.reads


async def test_with_masking_on_the_story_lines_keep_the_channel_addresses(engine: AsyncEngine) -> None:
    """Orch's walk of an email run (c-508): the story line read "Email from [email]:" beside an Email section that shows
    the sender. The lines keep where the email came from as the section does; what was read stays masked."""
    w = World(engine)
    parent, _ = await _notice(w, ssn="123-45-6789")
    lines = (await w.read(parent, mask={}))["story"]["lines"]
    assert lines[0]["text"] == "Email from registry@court.example: Notice of garnishment", lines[0]
    assert "[email]" not in json.dumps(lines) and "123-45-6789" not in json.dumps(lines), lines


def test_a_review_line_never_shows_an_unresolved_title() -> None:
    at = "2026-10-21T09:00:01Z"
    nodes = {"ask": {"id": "ask", "type": "ops.flow.humanReview", "typeVersion": 1, "name": "Reply",
                     "parameters": {"title": "Reply to {$.input.from}"}}}  # fmt: skip
    run: dict[str, Any] = {"id": "wfrun_x", "created_by": "a@x", "created_at": at, "input": {}}

    def asked(given: dict[str, Any]) -> str:
        step = {"nodeId": "ask", "iteration": 1, "status": "waiting", "port": None, "output": None, "input": given,
                "attempts": [{"startedAt": at, "finishedAt": None}]}  # fmt: skip
        return run_story.lines(run, [step], nodes, workflow="Levy", team="Operations", calls={}, who={})[1]["text"]

    assert asked({"title": "Reply to registry@court.example"}) == "Asked Operations: Reply to registry@court.example"
    assert asked({}) == "Asked Operations: Reply", "the step's name, not the template"
