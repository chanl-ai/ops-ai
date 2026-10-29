"""The email-to-reply levy workflows (c-532), scripts/sample-team/workflows/levy_reply_*.json, compiled and run on
fakes, by failure mode: the thank-you waits for a person, or the people's runs start before it; a person with no
account gets the hold path, or the no-account reply goes out without approval; exempt funds are sent to the hold
review; the hold is placed or the hold reply sent before a person approves it, or with an amount other than the one
worked out; a case the run answered stays open."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ops_engine import default_registry
from ops_engine.compiler import channel, compile_definition
from ops_engine.definition import parse, validate
from ops_engine.journal import MemoryJournal
from ops_engine.ports import Access, AgentRequest, AgentResult, EnginePorts, OpenedCase, StartedRun, ToolResult

FILES = Path(__file__).parents[4] / "scripts" / "sample-team" / "workflows"
NAMES = {
    "agent:levy": "ag_levy",
    "workflow:levy_reply_debtor": "levy_reply_debtor",
    "documentType:garnishment_notice": "garnishment_notice",
}


def flow(name: str) -> Any:
    """A sample team workflow file with its placeholders filled as the installer fills them."""
    text = (FILES / f"{name}.json").read_text()
    return parse(json.loads(re.sub(r"\{((?:agent|workflow|documentType):\w+)\}", lambda m: NAMES[m.group(1)], text)))


MARCUS = {"id": "CUS-1", "name": "Marcus Bell", "address": "12 Harbour Street, Halifax NS B3J 1A1", "ssnLast4": "4471"}
NOTICE = {"name": "Marcus Bell", "ssn_last4": "4471", "amount": 3250.0, "case_no": "NS-2026-GN-01187"}
GIVEN = {"from": "registry@court.test", "notice": "Notice of garnishment", "mailbox": "levies@harborpine.test"}


class Bank:
    def __init__(self, accounts: list[dict[str, Any]] | None = None, hold: float = 1140.55) -> None:
        self.accounts = [{"id": "CHQ-2219", "balance": 2140.55}] if accounts is None else accounts
        self.hold = hold
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        self.calls.append((operation, input, token))
        answers: dict[str, Any] = {
            "search_customers": [MARCUS] if "marcus" in str(input.get("query")).lower() else [],
            "list_accounts": self.accounts,
            "compute_levy_hold": {"holdAmount": self.hold, "accountId": "CHQ-2219", "reason": "Above exempt"},
            "place_hold": {"id": "HLD-1", "amount": input.get("amount")},
            "send_acknowledgement": {"status": "sent", "reference": "<ack@x>"},
            "send_reply": {"status": "sent", "reference": "<reply@x>"},
        }
        if operation not in answers:
            return ToolResult(False, reason="not expected here")
        return ToolResult(True, answers[operation])

    def sent(self) -> list[tuple[str, str]]:
        return [(op, str(i["body"])) for op, i, _ in self.calls if op.startswith("send_")]

    async def access(self, operation: str) -> Access:
        return "write" if operation in ("place_hold", "send_reply", "send_acknowledgement") else "read"

    async def mint(self, run_id: str, call: dict[str, Any], approval: dict[str, Any]) -> str | None:
        return "token"

    async def find(self, key: str, operation: str) -> ToolResult | None:
        return None


class Reviews:
    async def open(self, run_id: str, node_id: str, iteration: int, payload: dict[str, Any]) -> str:
        return f"{run_id}:{node_id}:{iteration}"


class Cases:
    def __init__(self) -> None:
        self.opened: list[str] = []
        self.status: dict[str, str] = {}
        self.notes: list[str] = []

    async def open(self, run_id: str, fields: dict[str, Any], key: str) -> OpenedCase:
        self.opened.append(str(fields["subject"]))
        return OpenedCase(f"case_{len(self.opened)}", True)

    async def add(
        self,
        run_id: str,
        case_id: str,
        note: str | None,
        fields: dict[str, Any] | None = None,
        *,
        status: str | None = None,
        key: str | None = None,
    ) -> None:
        if note:
            self.notes.append(note)
        if status:
            self.status[case_id] = status


class Desk:
    """The Levy Desk agent: checks the notice against the handbook."""

    def __init__(self) -> None:
        self.asked: list[AgentRequest] = []

    async def turn(self, request: AgentRequest) -> AgentResult:
        self.asked.append(request)
        return AgentResult(True, {"ok": True, "findings": "Complete; 1,000.00 protected (Levy handbook 2.1)."})


class Runs:
    def __init__(self) -> None:
        self.started: list[dict[str, Any]] = []

    async def start(self, parent_run_id: str, workflow: str, input: dict[str, Any], key: str) -> StartedRun:
        self.started.append(input)
        return StartedRun(f"wfrun_{len(self.started)}", True)


class Documents:
    def __init__(self, bank: Bank) -> None:
        self.bank = bank

    async def extract(self, run_id: str, file_id: str, request: dict[str, Any], *, key: str) -> dict[str, Any]:
        # The thank-you has not gone out while the notice is still being read.
        assert not self.bank.calls
        return {"id": "ext_1", "status": "done", "outcome": "ok", "records": [{"values": NOTICE}]}

    async def purge(self, run_id: str, file_id: str) -> dict[str, Any]:
        return {}


class Graph:
    def __init__(self, name: str, ports: EnginePorts, thread: str) -> None:
        self.g = compile_definition(
            flow(name), default_registry(), ports=ports, journal=MemoryJournal(), checkpointer=InMemorySaver()
        )
        self.cfg: Any = {"configurable": {"thread_id": thread, "run_id": thread, "lease_generation": 1}}

    async def go(self, value: Any) -> tuple[Any, dict[str, Any]]:
        await self.g.ainvoke(value, self.cfg, durability="sync")
        state = await self.g.aget_state(self.cfg)
        return state.interrupts, dict(state.values)


def approve(paused: Any) -> Command[Any]:
    return Command(resume={"decision": "approved", "by": "maya"})


def hold(paused: Any) -> Command[Any]:
    call = next(o for o in paused.value["options"] if o["name"] == "hold")["call"]
    return Command(resume={"decision": "approved", "option": "hold", "call": call, "approval": {"step": call["step"]}})


def person(bank: Bank, cases: Cases, desk: Desk | None = None) -> Graph:
    ports = EnginePorts(tools=bank, reviews=Reviews(), cases=cases, agents=desk or Desk())  # type: ignore[arg-type]
    return Graph("levy_reply_debtor", ports, "p1")


def test_both_workflows_pass_their_checks() -> None:
    for name in ("levy_reply_document", "levy_reply_debtor"):
        assert validate(flow(name), default_registry()) == [], name


async def test_the_sender_is_thanked_at_once_and_each_persons_run_is_told_it_was() -> None:
    bank, runs = Bank(), Runs()
    ports = EnginePorts(tools=bank, reviews=Reviews(), documents=Documents(bank), runs=runs)  # type: ignore[arg-type]
    given = {"fileId": "fil_1", "name": "notice.pdf", "from": "registry@court.test", "subject": "Notice NS-1"}
    paused, values = await Graph("levy_reply_document", ports, "d1").go({"input": given | {"mailbox": "m@x.test"}})
    assert not paused, "no person is asked before the thank-you"
    [(op, sent, token)] = bank.calls
    assert (op, sent["to"], sent["mailbox"], token) == ("send_acknowledgement", "registry@court.test", "m@x.test", None)
    assert sent["body"] == "We received your notice and are working on it."
    [started] = runs.started
    assert started["record"] == NOTICE and started["acknowledgement"]["status"] == "sent"
    assert values[channel("answered")]["out"]["outcome"] == "answering"


async def test_a_person_with_accounts_waits_for_the_hold_review_with_the_worked_out_hold_and_nothing_sent() -> None:
    bank, cases, desk = Bank(), Cases(), Desk()
    [paused], _ = await person(bank, cases, desk).go({"input": GIVEN | {"record": NOTICE}})
    offered = next(o for o in paused.value["options"] if o["name"] == "hold")["call"]
    assert offered["input"] == {"account_id": "CHQ-2219", "amount": 1140.55, "reason": "NS-2026-GN-01187"}
    assert [op for op, _, _ in bank.calls] == ["search_customers", "list_accounts", "compute_levy_hold"]
    [(_, calc_in, _)] = [c for c in bank.calls if c[0] == "compute_levy_hold"]
    assert calc_in == {"document": NOTICE, "accounts": bank.accounts}
    assert "handbook" in desk.asked[0].message and paused.value["draft"]["check"]["ok"] is True
    assert cases.opened == ["Levy notice: Marcus Bell (NS-2026-GN-01187)"]
    assert any(n.startswith("Sent to registry@court.test without approval") for n in cases.notes)


async def test_the_hold_reply_waits_for_its_own_approval_and_then_resolves_the_case() -> None:
    bank, cases = Bank(), Cases()
    g = person(bank, cases)
    [paused], _ = await g.go({"input": GIVEN | {"record": NOTICE}})
    [asked], _ = await g.go(hold(paused))
    assert ("place_hold", {"account_id": "CHQ-2219", "amount": 1140.55, "reason": "NS-2026-GN-01187"}, "token") in [
        (op, i, t) for op, i, t in bank.calls
    ]
    assert asked.value["node"] == "ask_held" and bank.sent() == [], "the hold reply waits for a person"
    _, values = await g.go(approve(asked))
    assert bank.sent() == [("send_reply", "The hold has been applied.")]
    assert values[channel("held")]["out"]["outcome"] == "held" and cases.status == {"case_1": "resolved"}


async def test_a_person_with_no_account_gets_the_no_account_reply_after_approval_and_no_hold() -> None:
    for bank, opened in (
        (Bank(), "No account: Jordan Whitfield (MB-1)"),
        (Bank(accounts=[]), "Levy notice: Marcus Bell (MB-1)"),
    ):
        cases = Cases()
        record = (NOTICE | {"name": "Jordan Whitfield"}) if opened.startswith("No") else NOTICE
        g = person(bank, cases)
        [asked], _ = await g.go({"input": GIVEN | {"record": record | {"case_no": "MB-1"}}})
        assert asked.value["node"] == "ask_none" and bank.sent() == [], opened
        _, values = await g.go(approve(asked))
        [(op, body)] = bank.sent()
        assert op == "send_reply" and "holds no account for" in body and "MB-1" in body, body
        assert not any(o in ("compute_levy_hold", "place_hold") for o, _, _ in bank.calls), opened
        assert cases.opened == [opened] and cases.status == {"case_1": "resolved"}, opened
        assert values[channel("no_account")]["out"]["outcome"] == "no_account"


async def test_funds_the_code_finds_exempt_get_the_exempt_reply_after_approval_and_no_hold_review() -> None:
    bank, cases = Bank(hold=0), Cases()
    g = person(bank, cases)
    [asked], _ = await g.go({"input": GIVEN | {"record": NOTICE}})
    assert asked.value["node"] == "ask_exempt" and bank.sent() == []
    _, values = await g.go(approve(asked))
    [(op, body)] = bank.sent()
    assert op == "send_reply" and "exempt" in body and "NS-2026-GN-01187" in body, body
    assert "place_hold" not in [o for o, _, _ in bank.calls] and cases.status == {"case_1": "resolved"}
    assert values[channel("exempt")]["out"]["outcome"] == "exempt"
