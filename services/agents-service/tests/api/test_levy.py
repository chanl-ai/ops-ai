"""A levy notice from the mailbox to customer cases and holds (c-057 T004, T005), by failure mode: a person matched
on name alone becoming a case, a notice with nobody in it opening cases, a hold or note running without the
reviewer's token, a decision that is not one of the step's options, the bank's 422 on a hold being retried or lost,
and the parent not listing what its children did."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agent_kernel.ports import ToolOutcome
from ops_agents.activities.tools import LocalToolExecutor
from ops_agents.api.app import create_app
from ops_agents.api.deps import Runtime
from ops_agents.api.runs import config, resolve
from ops_agents.graphs import definition as graphs_definition
from ops_agents.graphs.definition import record_matches
from ops_agents.store.base import metadata
from ops_agents.store.graphs import graph_threads, graph_versions
from ops_policy import input_hash
from ops_policy.approval import binding_of
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model, sse_events, step_up

NOTICE: dict[str, Any] = json.loads((SEED.parent / "mailbox" / "levy_notice.json").read_text())
MAYA = "m.okafor@harborpine.example"


class Stack:
    def __init__(self, client: AsyncClient, rt: Runtime) -> None:
        self.client, self.rt = client, rt

    async def intake(self, email: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        r = await self.client.post("/v1/threads", json={"graph": "levy-intake", "metadata": {}})
        assert r.status_code == 201, r.text
        tid = r.json()["data"]["threadId"]
        res = await self.client.post(f"/v1/threads/{tid}/runs/stream", json={"input": {"email": email}})
        assert res.status_code == 200, res.text
        return tid, sse_events(res.text)

    async def notice(self) -> tuple[str, list[dict[str, Any]]]:
        """The fixture notice as the mailbox adapter hands it to the graph: the PDF stored under a file id."""
        assert self.rt.channels is not None
        (att,) = NOTICE["attachments"]
        await self.rt.channels.put_file(
            "file_levy_pdf", name=att["name"], content_type=att["contentType"], content=att["contentBytes"], sha256="x"
        )
        email = {
            "sender": NOTICE["from"]["emailAddress"]["address"],
            "subject": NOTICE["subject"],
            "body": NOTICE["body"]["content"],
            "attachments": [{"name": att["name"], "file_id": "file_levy_pdf"}],
        }
        return await self.intake(email)

    async def state(self, tid: str) -> dict[str, Any]:
        return (await self.client.get(f"/v1/threads/{tid}/state")).json()["data"]

    async def children(self, parent: str) -> list[dict[str, Any]]:
        assert self.rt.graph_store is not None
        return [t for t in await self.rt.graph_store.threads("levy-case") if t["parent_thread_id"] == parent]

    async def decide(self, tid: str, decision: str, *, confirm: bool = True, **extra: Any) -> Any:
        """Maya decides. A hold asks for a step-up (place_hold's policy), sent unless `confirm` is off."""
        body: dict[str, Any] = {"decision": decision, **extra}
        if decision == "hold" and confirm:
            body["stepUpToken"] = await step_up(self.client, MAYA)
        return await self.client.post(f"/reviews/{tid}/decision", json=body, headers={"X-Dev-User": MAYA})

    async def review(self, tid: str) -> dict[str, Any]:
        r = await self.client.get(f"/reviews/{tid}", headers={"X-Dev-User": MAYA})
        assert r.status_code == 200, r.text
        return r.json()["data"]

    def executor(self) -> LocalToolExecutor:
        assert self.rt.graph_deps is not None
        return cast(LocalToolExecutor, self.rt.graph_deps.ports.tools)

    def gateway_like(self) -> list[dict[str, Any]]:
        """Makes the local tool port check a write's token the way the gateway's policy does: minted for this thread,
        this tool and the digest of the input it receives. A token for another call is refused, not run. Returns the
        list of refusals, so a test can show what was turned away."""
        self.rt.gateway = True
        executor, real, refused = self.executor(), self.executor().execute, cast(list[dict[str, Any]], [])
        key = self.rt.settings.review_key.get_secret_value()

        async def checked(
            tool: str, arguments: dict[str, Any], *, key_: str, approval_token: str | None
        ) -> ToolOutcome:
            if tool in ("place_hold", "add_customer_note"):
                try:
                    bound = binding_of(approval_token or "", key)
                except Exception:  # a malformed or missing token is the refusal
                    bound = None
                if bound is None or bound.tool != tool or bound.inputHash != input_hash(arguments):
                    refused.append({"tool": tool, "input": arguments, "token": approval_token})
                    return ToolOutcome(False, {"error": {"code": "forbidden", "status": 403, "message": "token"}})
            return await real(tool, arguments, key=key_, approval_token=approval_token)

        async def execute(tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None) -> ToolOutcome:
            return await checked(tool, arguments, key_=key, approval_token=approval_token)

        executor.execute = execute  # type: ignore[method-assign]
        return refused


@pytest.fixture
async def stack() -> AsyncIterator[Stack]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    app = create_app(
        Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED),
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        knowledge=fixture_knowledge(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://m") as client,
    ):
        yield Stack(client, cast(Runtime, app.state.runtime))


# ── T004: records, matching, cases ──


async def test_the_notice_opens_one_case_per_matched_customer(stack: Stack) -> None:
    parent, events = await stack.notice()
    values = (await stack.state(parent))["values"]
    assert [r["name"] for r in values["records"]] == ["Marcus Bell", "Priya Natarajan", "Jordan Whitfield"]
    assert values["records"][0]["ssn_last4"] == "4471" and values["records"][1]["case_no"] == "ON-2026-GN-04421"
    assert values["status"] == "cases_opened"
    # Marcus matches by name and address, Priya by name and the last four alone (her address on file differs).
    assert sorted(m["customer"]["customerId"] for m in values["matches"]) == ["CUS-1001", "CUS-4471"]
    assert all(m["accounts"] for m in values["matches"]), "each case carries the customer's accounts"
    # Jordan Whitfield is on file under another address and SSN: a candidate for a person to read, not a case.
    assert [c["record"]["name"] for c in values["candidates"]] == ["Jordan Whitfield"]
    assert values["candidates"][0]["customers"][0]["customerId"] == "CUS-7710"
    assert values.get("unmatched", []) == []
    children = await stack.children(parent)
    assert len(children) == 2 and {c["meta"]["customerId"] for c in children} == {"CUS-1001", "CUS-4471"}
    assert sorted(c["customerId"] for c in values["children"]) == ["CUS-1001", "CUS-4471"]
    assert all(c["status"] == "waiting_review" for c in values["children"])
    nodes = [e["node"] for e in events if e["event"] == "node_start"]
    assert nodes.count("match") == 3, nodes
    child = await stack.state(children[0]["id"])
    options = child["interrupt"]["payload"]["options"]
    assert [o["name"] for o in options] == ["hold", "flag"]
    # The hold declares what a reviewer may set, from place_hold's own schema, with the notice's amount proposed.
    (amount,) = options[0]["inputs"]
    assert (amount["name"], amount["type"], amount["required"], amount["minimum"]) == ("amount", "number", True, 0.01)
    assert amount["default"] == options[0]["call"]["input"]["amount"] and options[1]["inputs"] == []
    assert child["values"]["customer"]["customerId"] == children[0]["meta"]["customerId"]


def test_a_name_alone_is_never_a_match() -> None:
    record = {"name": "Jordan Whitfield", "address": "301 Pine Avenue, Winnipeg MB R3B 2K7", "ssn_last4": "1180"}
    same_name = {"name": "Jordan Whitfield", "address": "9 Elm Crescent, Brandon MB", "ssnLast4": "5555"}
    assert record_matches(record, same_name, min_address_chars=6) is False
    assert record_matches(record, {**same_name, "ssnLast4": "1180"}, min_address_chars=6) is True
    assert record_matches(record, {**same_name, "address": "301 Pine Avenue"}, min_address_chars=6) is True
    # A short address fragment is not evidence, and an address without the name is not either.
    assert record_matches(record, {**same_name, "address": "301 P"}, min_address_chars=6) is False
    assert (
        record_matches({**record, "name": "J. Whitfield"}, {**same_name, "ssnLast4": "1180"}, min_address_chars=6)
        is False
    )


async def test_a_notice_naming_nobody_needs_a_manual_read(stack: Stack) -> None:
    parent, _ = await stack.intake(
        {"sender": "registry@court.example", "subject": "Garnishment", "body": "See attached.", "attachments": []}
    )
    values = (await stack.state(parent))["values"]
    assert values["status"] == "needs_manual_read" and values["record_count"] == 0
    assert "See attached." in values["text"]
    assert await stack.children(parent) == []


async def test_records_that_match_nobody_leave_the_parent_as_candidates_only(stack: Stack) -> None:
    body = (
        "Debtor 1: Nobody Known\nAddress: 1 Nowhere Road, Regina SK S4P 3Y2\nSSN (last four): ***-**-0000\n"
        "Amount: 10.00\nCourt: Court of Nowhere\nCase No: SK-2026-GN-00001"
    )
    parent, _ = await stack.intake(
        {"sender": "registry@court.example", "subject": "Garnishment", "body": body, "attachments": []}
    )
    values = (await stack.state(parent))["values"]
    assert values["record_count"] == 1 and values["status"] == "candidates_only"
    assert [u["name"] for u in values["unmatched"]] == ["Nobody Known"] and values["children"] == []
    assert await stack.children(parent) == []


async def test_a_search_the_bank_cannot_answer_is_an_error_on_the_parent(stack: Stack) -> None:
    executor = stack.executor()
    real = executor.execute

    async def bank_down(tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None) -> ToolOutcome:
        if tool == "search_customers":
            return ToolOutcome(False, "The tool gateway refused this call: search_customers is not offered.")
        return await real(tool, arguments, key=key, approval_token=approval_token)

    executor.execute = bank_down  # type: ignore[method-assign]
    parent, _ = await stack.notice()
    values = (await stack.state(parent))["values"]
    assert values["status"] == "candidates_only" and values["matches"] == []
    assert all("not offered" in u["error"] for u in values["unmatched"]) and len(values["unmatched"]) == 3


# ── T005: hold and flag decisions ──


async def test_hold_places_the_hold_with_the_decisions_call_and_amount(stack: Stack) -> None:
    parent, _ = await stack.notice()
    case = next(c for c in await stack.children(parent) if c["meta"]["customerId"] == "CUS-1001")["id"]
    turned_away = stack.gateway_like()
    refused = await stack.decide(case, "approved")
    assert refused.status_code == 400 and "hold, flag" in refused.json()["error"]["message"]
    r = await stack.decide(case, "hold", inputs={"amount": 1500})
    assert r.status_code == 200, r.text
    values = (await stack.state(case))["values"]
    # The token was minted over the reviewer's 1500, not the notice's 3250: a token for any other call is refused.
    assert turned_away == [], turned_away
    bound = binding_of(values["decision"]["approval_token"], stack.rt.settings.review_key.get_secret_value())
    assert bound.inputHash == input_hash(values["decision"]["call"]["input"]) and bound.tool == "place_hold"
    assert values["status"] == "held" and values["hold"]["status"] == "completed"
    # Recorded as approved, with the option beside it: Reviews keeps its statuses.
    assert (values["decision"]["decision"], values["decision"]["option"]) == ("approved", "hold")
    decided = await stack.review(case)
    assert (decided["status"], decided["option"]) == ("approved", "hold")
    assert values["decision"]["call"]["input"] == {
        "accountId": "CHQ-1001",
        "amount": 1500.0,
        "reason": "Garnishment NS-2026-GN-01187, Nova Scotia Supreme Court",
    }
    assert values["tool_error"] is None
    # The parent lists the child's outcome.
    assert stack.rt.graph_store is not None
    listed = (await stack.rt.graph_store.meta(parent))["children"]
    assert [(c["customerId"], c["outcome"]) for c in listed] == [("CUS-1001", "held")]
    parent_values = (await stack.state(parent))["values"]
    assert parent_values["status"] == "cases_opened"


async def test_flag_writes_the_note_only_with_the_decisions_token(stack: Stack) -> None:
    parent, _ = await stack.notice()
    case = next(c for c in await stack.children(parent) if c["meta"]["customerId"] == "CUS-4471")["id"]
    turned_away = stack.gateway_like()
    # The write refuses to run without a token: the tool port, which the flag step calls, is the seam.
    bare = await stack.executor().execute(
        "add_customer_note", {"customerId": "CUS-4471", "text": "x"}, key="k", approval_token=None
    )
    assert bare.ok is False and len(turned_away) == 1
    # The decision mints the token for the note call alone; the resume carries it and the port accepts it.
    r = await stack.decide(case, "flag")
    assert r.status_code == 200, r.text
    values = (await stack.state(case))["values"]
    assert values["status"] == "flagged" and values["note"]["status"] == "completed"
    assert len(turned_away) == 1, "the minted token was accepted for the note call"
    bound = binding_of(values["decision"]["approval_token"], stack.rt.settings.review_key.get_secret_value())
    assert (bound.thread, bound.tool, bound.approvers) == (case, "add_customer_note", [MAYA])
    assert values["decision"]["call"]["input"]["customerId"] == "CUS-4471"
    assert stack.rt.graph_store is not None
    assert [(c["customerId"], c["outcome"]) for c in (await stack.rt.graph_store.meta(parent))["children"]] == [
        ("CUS-4471", "flagged")
    ]


async def test_a_hold_over_the_balance_shows_the_422_and_waits_for_a_new_decision(stack: Stack) -> None:
    parent, _ = await stack.notice()
    case = next(c for c in await stack.children(parent) if c["meta"]["customerId"] == "CUS-1001")["id"]
    executor = stack.executor()
    real, calls = executor.execute, cast(list[dict[str, Any]], [])

    async def bank_refuses(
        tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        if tool == "place_hold":
            calls.append(arguments)
            error = {
                "code": "upstream_error",
                "status": 422,
                "side": "upstream",
                "message": "hold of 9000.00 exceeds the available balance of 2140.55",
            }
            return ToolOutcome(False, {"error": error})
        return await real(tool, arguments, key=key, approval_token=approval_token)

    executor.execute = bank_refuses  # type: ignore[method-assign]
    r = await stack.decide(case, "hold", inputs={"amount": 9000})
    assert r.status_code == 200, r.text
    state = await stack.state(case)
    assert state["values"]["tool_error"] == {
        "tool": "place_hold",
        "status": 422,
        "code": "upstream_error",
        "message": "hold of 9000.00 exceeds the available balance of 2140.55",
        # The call in words for the page (c-500), from the decision that carried it, never the tool's name.
        "action": "Hold 9,000 on CHQ-1001",
    }
    assert state["values"].get("hold") is None and "status" not in state["values"]
    assert state["interrupt"]["payload"]["error"]["status"] == 422, "the review shows the bank's answer"
    assert len(calls) == 1, "nothing retried the hold"
    row = (await stack.client.get(f"/runs/{case}")).json()["data"]
    assert row["status"] == "waiting_review"
    assert stack.rt.graph_store is not None
    listed: list[dict[str, Any]] = list((await stack.rt.graph_store.meta(parent)).get("children") or [])
    assert case not in {c["threadId"] for c in listed}, "a failed hold is not an outcome"
    # A new decision is a new call with its own step: the reviewer flags instead.
    executor.execute = real  # type: ignore[method-assign]
    r = await stack.decide(case, "flag")
    assert r.status_code == 200, r.text
    values = (await stack.state(case))["values"]
    assert values["status"] == "flagged" and values["tool_error"] is None
    assert values["decision"]["call"]["step"].endswith(":flag:2")


# ── T012: what the console needed and the server lacked ──


async def test_a_one_approver_hold_still_asks_for_a_step_up(stack: Stack) -> None:
    parent, _ = await stack.notice()
    case = next(c for c in await stack.children(parent) if c["meta"]["customerId"] == "CUS-1001")["id"]
    row = await stack.review(case)
    assert row["stepUp"] is True, "place_hold's policy asks for one with a single approver"
    assert [(o["name"], o["stepUp"]) for o in row["options"]] == [("hold", True), ("flag", False)]
    without = await stack.decide(case, "hold", confirm=False, inputs={"amount": 100})
    assert without.status_code == 422 and without.json()["error"]["code"] == "step_up_required", without.text
    assert "status" not in (await stack.state(case))["values"], "nothing ran"
    flagged = await stack.decide(case, "flag")
    assert flagged.status_code == 200, "a note asks for none"


async def test_inputs_are_validated_against_the_options_declaration(stack: Stack) -> None:
    parent, _ = await stack.notice()
    case = next(c for c in await stack.children(parent) if c["meta"]["customerId"] == "CUS-1001")["id"]
    unknown = await stack.decide(case, "hold", inputs={"reason": "my own"})
    assert unknown.status_code == 400 and "not an input a reviewer may set" in unknown.json()["error"]["message"]
    typed = await stack.decide(case, "hold", inputs={"amount": "lots"})
    assert typed.status_code == 400 and "must be a number" in typed.json()["error"]["message"]
    low = await stack.decide(case, "hold", inputs={"amount": 0})
    assert low.status_code == 400 and "at least 0.01" in low.json()["error"]["message"]
    no_amount = await stack.decide(case, "flag", amount=5)
    assert no_amount.status_code == 400 and "takes no amount" in no_amount.json()["error"]["message"]
    assert (await stack.state(case))["interrupt"] is not None, "still waiting"


async def test_the_review_row_carries_the_subject_amount_options_and_an_honest_sla(stack: Stack) -> None:
    parent, _ = await stack.notice()
    case = next(c for c in await stack.children(parent) if c["meta"]["customerId"] == "CUS-1001")["id"]
    row = await stack.review(case)
    assert row["title"].startswith("Levy NS-2026-GN-01187: Marcus Bell")
    assert row["amount"] == 3250.0 and row["customer"] == "Marcus Bell"
    assert [o["name"] for o in row["options"]] == ["hold", "flag"] and row["calls"]["hold"]["tool"] == "place_hold"
    assert row["slaMinutes"] is None, "the levy review sets no SLA, so no time is claimed"


async def test_a_childs_outcome_reaches_the_parents_state_and_run_row(stack: Stack) -> None:
    parent, _ = await stack.notice()
    cases = await stack.children(parent)
    marcus = next(c for c in cases if c["meta"]["customerId"] == "CUS-1001")["id"]
    before = (await stack.state(parent))["values"]["children"]
    assert all(c["status"] == "waiting_review" for c in before)
    assert (await stack.decide(marcus, "hold", inputs={"amount": 10})).status_code == 200
    after = {c["threadId"]: c for c in (await stack.state(parent))["values"]["children"]}
    assert after[marcus]["outcome"] == "held" and after[marcus]["status"] == "finished"
    assert after[marcus]["hold"]["status"] == "completed"
    # Written into the checkpoint itself, not only read over it from the meta.
    _, graph = await resolve(stack.rt, parent)
    raw = (await graph.aget_state(config(parent))).values["children"]
    assert next(c for c in raw if c["threadId"] == marcus)["outcome"] == "held"
    run = (await stack.client.get(f"/runs/{parent}", headers={"X-Dev-User": MAYA})).json()["data"]
    assert next(c for c in run["children"] if c["threadId"] == marcus)["outcome"] == "held"
    child_run = (await stack.client.get(f"/runs/{marcus}", headers={"X-Dev-User": MAYA})).json()["data"]
    assert child_run["parentThreadId"] == parent


async def test_runs_filter_by_parent(stack: Stack) -> None:
    parent, _ = await stack.notice()
    other, _ = await stack.intake(
        {"sender": "registry@court.example", "subject": "Garnishment", "body": "See attached.", "attachments": []}
    )
    r = await stack.client.get("/runs", params={"view": "open", "parent": parent}, headers={"X-Dev-User": MAYA})
    assert r.status_code == 200, r.text
    rows = r.json()["data"]["data"]
    assert len(rows) == 2 and all(row["parentThreadId"] == parent for row in rows)
    assert {row["workflowId"] for row in rows} == {"levy-case"}
    none = await stack.client.get("/runs", params={"view": "open", "parent": other}, headers={"X-Dev-User": MAYA})
    assert none.json()["data"]["data"] == []


async def paused_with_names(stack: Stack, monkeypatch: Any) -> str:
    """Marcus's case paused the way rows did before declarations existed: options stored as names."""

    async def names_only(deps: Any, options: list[Any], calls: Any) -> list[Any]:
        return [graphs_definition.option_name(o) for o in options]

    monkeypatch.setattr(graphs_definition, "option_declarations", names_only)
    parent, _ = await stack.notice()
    monkeypatch.undo()
    case = next(c for c in await stack.children(parent) if c["meta"]["customerId"] == "CUS-1001")["id"]
    _, graph = await resolve(stack.rt, case)
    stored = (await graph.aget_state(config(case))).interrupts[0].value
    assert stored["options"] == ["hold", "flag"], "the row holds names, as the old rows do"
    return case


async def test_a_review_paused_with_name_only_options_lists_and_decides(stack: Stack, monkeypatch: Any) -> None:
    """Rows paused before declarations existed store options as names (the shared stack's first levy cases). The
    declaration is the workflow version's, so the view and decide resolve the names against it; a 500 here hid the
    whole Reviews page."""
    case = await paused_with_names(stack, monkeypatch)
    listed = await stack.client.get("/reviews", params={"view": "open"}, headers={"X-Dev-User": MAYA})
    assert listed.status_code == 200, listed.text
    row = next(r for r in listed.json()["data"]["data"] if r["id"] == case)
    assert [o["name"] for o in row["options"]] == ["hold", "flag"] and row["optionsError"] is None
    assert row["options"][0]["inputs"][0]["name"] == "amount"
    assert (await stack.review(case))["options"][1]["name"] == "flag", "the detail path resolves too"
    state = await stack.state(case)
    assert [o["name"] for o in state["interrupt"]["payload"]["options"]] == ["hold", "flag"]
    r = await stack.decide(case, "hold", inputs={"amount": 25})
    assert r.status_code == 200, r.text
    assert (await stack.state(case))["values"]["status"] == "held"


async def test_a_review_whose_options_cannot_be_declared_is_listed_with_the_reason(
    stack: Stack, monkeypatch: Any
) -> None:
    """The pinned version's step no longer declares an option the row stored: the review is listed with the reason
    and cannot be decided with that option, never dropped or a 500."""
    case = await paused_with_names(stack, monkeypatch)
    assert stack.rt.graph_store is not None
    stored = await stack.rt.graph_store.version("levy-case", 1)
    assert stored is not None
    edited = dict(stored["definition"])
    edited["nodes"] = [
        {**n, "config": {"options": [{"name": "flag"}]}} if n["id"] == "review" else n for n in edited["nodes"]
    ]
    # The thread stays pinned to a consistent version: the version's digest and the thread's follow the edit, as a
    # migration of the stored definition would leave them (an inconsistent digest is a different refusal).
    digest = graphs_definition.WorkflowDefinition.model_validate(edited).digest()
    async with stack.rt.graph_store.engine.begin() as c:
        await c.execute(
            graph_versions.update()
            .where(graph_versions.c.name == "levy-case", graph_versions.c.version == 1)
            .values(definition=edited, digest=digest)
        )
        await c.execute(graph_threads.update().where(graph_threads.c.id == case).values(digest=digest))
    listed = await stack.client.get("/reviews", params={"view": "open"}, headers={"X-Dev-User": MAYA})
    assert listed.status_code == 200, listed.text
    row = next(r for r in listed.json()["data"]["data"] if r["id"] == case)
    assert row["options"] is None and "hold" in row["optionsError"] and "declaration" in row["optionsError"]
    assert "hold" in (await stack.state(case))["interrupt"]["payload"]["optionsError"]
    refused = await stack.decide(case, "hold", inputs={"amount": 25})
    assert refused.status_code == 400 and "cannot be decided" in refused.json()["error"]["message"]
