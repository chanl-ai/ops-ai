"""The levy workflows on the runner (c-210), by failure mode: a definition that no longer passes its checks; a debtor
found by name alone reaching a review; a matched debtor's review offering a hold on the wrong account or amount; a
debtor's case not naming the debtor, the court case and the matched customer (c-219); a levy notice read in Read one
levy document going to a person instead of a case per debtor (workflows-run-5).
The definitions are the dev seed's (seed/engine_workflows.json). The bank answers as
`services/tools-service/scripts/fake_bank` does."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ops_engine import default_registry
from ops_engine.compiler import channel, compile_definition
from ops_engine.definition import parse, validate
from ops_engine.journal import MemoryJournal
from ops_engine.ports import Access, EnginePorts, OpenedCase, StartedRun, ToolResult

SEED = {w["id"]: w for w in json.loads((Path(__file__).parents[2] / "seed" / "engine_workflows.json").read_text())}


def levy(name: str) -> Any:
    """A levy workflow from the dev seed, without the seed's owning team."""
    return parse({k: v for k, v in SEED[name].items() if k != "teamId"})


CASE = levy("levy_case")
MARCUS = {"id": "CUS-1", "name": "Marcus Bell", "address": "12 Harbour Street, Halifax NS B3J 1A1", "ssnLast4": "4471"}
ACCOUNTS = [{"id": "CHQ-2219", "customerId": "CUS-1", "balance": 5000.0}]


class Bank:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        self.calls.append(operation)
        if operation == "search_customers":
            return ToolResult(True, [MARCUS] if "marcus" in str(input["query"]).lower() else [])
        if operation == "list_accounts":
            return ToolResult(True, ACCOUNTS)
        return ToolResult(False, reason="not expected here")

    async def access(self, operation: str) -> Access:
        return "read"

    async def mint(self, run_id: str, call: dict[str, Any], approval: dict[str, Any]) -> str | None:
        return None

    async def find(self, key: str, operation: str) -> ToolResult | None:
        return None


class Reviews:
    async def open(self, run_id: str, node_id: str, iteration: int, payload: dict[str, Any]) -> str:
        return f"{run_id}:{node_id}:{iteration}"


class Cases:
    def __init__(self) -> None:
        self.opened: list[dict[str, Any]] = []

    async def open(self, run_id: str, fields: dict[str, Any], key: str) -> OpenedCase:
        self.opened.append(fields)
        return OpenedCase(f"case_{len(self.opened)}", True)

    async def add(self, run_id: str, case_id: str, note: str | None, fields: dict[str, Any] | None = None) -> None:
        return None


def test_the_mailbox_workflows_pass_their_checks_and_belong_to_a_team() -> None:
    for name in ("levy_intake", "levy_case", "mail_intake", "mail_document", "levy_read_one"):
        assert validate(levy(name), default_registry()) == [], name
        assert SEED[name]["teamId"] == "team_ops", "an Email received trigger binds only a team's workflow"


async def run(record: dict[str, Any], cases: Cases | None = None) -> tuple[Any, dict[str, Any], Bank]:
    bank = Bank()
    ports = EnginePorts(tools=bank, reviews=Reviews(), cases=cases or Cases())
    g = compile_definition(CASE, default_registry(), ports=ports, journal=MemoryJournal(), checkpointer=InMemorySaver())
    cfg: Any = {"configurable": {"thread_id": "lc1", "run_id": "lc1", "lease_generation": 1}}
    await g.ainvoke({"input": {"record": record}}, cfg, durability="sync")
    state = await g.aget_state(cfg)
    return state.interrupts, dict(state.values), bank


async def test_a_matched_debtor_waits_for_hold_or_flag_on_the_first_account_for_the_notices_amount() -> None:
    record = {"name": "Marcus Bell", "address": "12 Harbour Street, Halifax", "ssn_last4": "", "amount": 3250.0}
    interrupts, _, bank = await run(record | {"case_no": "NS-2026-GN-01187"})
    [paused] = interrupts
    hold = next(o for o in paused.value["options"] if o["name"] == "hold")["call"]
    assert hold["tool"] == "place_hold"
    assert hold["input"] == {"account_id": "CHQ-2219", "amount": 3250.0, "reason": "NS-2026-GN-01187"}
    assert [o["name"] for o in paused.value["options"]] == ["hold", "flag"]
    assert bank.calls == ["search_customers", "list_accounts"]


async def test_a_debtor_found_by_name_alone_ends_not_matched_with_the_candidates() -> None:
    record = {"name": "Marcus Bell", "address": "9 Other Road, Toronto", "ssn_last4": "0000", "amount": 10.0}
    interrupts, values, bank = await run(record | {"case_no": "X"})
    assert not interrupts and bank.calls == ["search_customers"]
    ended = values[channel("not_matched")]["out"]
    assert ended["outcome"] == "not_matched" and ended["output"]["candidates"] == [MARCUS]


async def test_each_debtor_opens_a_case_naming_the_debtor_the_court_case_and_the_matched_customer() -> None:
    matched, unmatched = Cases(), Cases()
    record = {"name": "Marcus Bell", "address": "12 Harbour Street, Halifax", "ssn_last4": "", "amount": 3250.0}
    [paused], _, _ = await run(record | {"case_no": "NS-2026-GN-01187"}, matched)
    stranger = {"name": "Jordan Whitfield", "address": "1 Elm St", "ssn_last4": "1", "amount": 5.0, "case_no": "X-9"}
    await run(stranger, unmatched)
    assert matched.opened == [
        {
            "subject": "Levy notice: Marcus Bell (NS-2026-GN-01187)",
            "priority": "high",
            "customerId": "CUS-1",
            "customerName": "Marcus Bell",
        }
    ]
    assert paused.value["draft"]["caseId"] == "case_1"
    assert unmatched.opened == [
        {"subject": "Levy notice: Jordan Whitfield (X-9)", "priority": "high", "customerName": "Jordan Whitfield"}
    ]


class Documents:
    """A detected read of a levy notice naming two debtors, as documents-service answers it."""

    async def extract(self, run_id: str, file_id: str, request: dict[str, Any], *, key: str) -> dict[str, Any]:
        debtors = [{"name": "Marcus Bell", "case_no": "NS-1"}, {"name": "Jordan Whitfield", "case_no": "NS-1"}]
        return {
            "id": "ext_1",
            "status": "done",
            "outcome": "ok",
            "documentType": {"id": "levy_notice", "version": 1},
            "classification": {"typeId": "levy_notice", "confidence": 0.98},
            "records": [{"values": d} for d in debtors],
        }

    async def purge(self, run_id: str, file_id: str) -> dict[str, Any]:
        return {}


class Runs:
    def __init__(self) -> None:
        self.started: list[tuple[str, dict[str, Any]]] = []

    async def start(self, parent_run_id: str, workflow: str, input: dict[str, Any], key: str) -> StartedRun:
        self.started.append((workflow, input))
        return StartedRun(f"wfrun_{len(self.started)}", True)


async def test_a_levy_notice_read_starts_a_levy_case_per_debtor_instead_of_going_to_a_person() -> None:
    runs = Runs()
    ports = EnginePorts(tools=Bank(), reviews=Reviews(), documents=Documents(), runs=runs)  # type: ignore[arg-type]
    one = levy("levy_read_one")
    g = compile_definition(one, default_registry(), ports=ports, journal=MemoryJournal(), checkpointer=InMemorySaver())
    cfg: Any = {"configurable": {"thread_id": "r1", "run_id": "r1", "lease_generation": 1}}
    await g.ainvoke({"input": {"fileId": "fil_1", "name": "levy_notice.pdf"}}, cfg, durability="sync")
    values = dict((await g.aget_state(cfg)).values)
    assert values[channel("notices_done")]["out"]["outcome"] == "levy_notice"
    assert [(w, i["record"]["name"], i["fileId"]) for w, i in runs.started] == [
        ("levy_case", "Marcus Bell", "fil_1"),
        ("levy_case", "Jordan Whitfield", "fil_1"),
    ]


class DoubtfulDocuments(Documents):
    """The same notice read below the floor: documents-service answers review, the debtors as records and no fields of
    a single read, so Check the read has nothing of one record to edit."""

    async def extract(self, run_id: str, file_id: str, request: dict[str, Any], *, key: str) -> dict[str, Any]:
        return await super().extract(run_id, file_id, request, key=key) | {"outcome": "review", "needsReview": [1]}


async def test_a_doubtful_levy_notice_checked_by_a_person_still_starts_a_levy_case_per_debtor() -> None:
    """c-313: read:review -> Check the read -> approve -> By kind levy_notice -> a case per debtor named."""
    runs = Runs()
    ports = EnginePorts(tools=Bank(), reviews=Reviews(), documents=DoubtfulDocuments(), runs=runs)  # type: ignore[arg-type]
    one = levy("levy_read_one")
    g = compile_definition(one, default_registry(), ports=ports, journal=MemoryJournal(), checkpointer=InMemorySaver())
    cfg: Any = {"configurable": {"thread_id": "r2", "run_id": "r2", "lease_generation": 1}}
    await g.ainvoke({"input": {"fileId": "fil_1", "name": "levy_notice.pdf"}}, cfg, durability="sync")
    [paused] = (await g.aget_state(cfg)).interrupts
    assert paused.value["node"] == "check" and not runs.started, "the doubtful read waits for a person first"
    await g.ainvoke(Command(resume={"decision": "approved", "by": "maya"}), cfg, durability="sync")
    values = dict((await g.aget_state(cfg)).values)
    assert values[channel("notices_done")]["out"]["outcome"] == "levy_notice"
    assert [(w, i["record"]["name"]) for w, i in runs.started] == [
        ("levy_case", "Marcus Bell"),
        ("levy_case", "Jordan Whitfield"),
    ]
