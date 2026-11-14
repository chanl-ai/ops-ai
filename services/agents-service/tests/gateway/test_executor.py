# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
"""The Runtime's side: every tool call, read or write, goes to the gateway with the run's thread and step."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ops_agents.activities.gateway import (
    RUN_CONTEXT,
    TOKEN_MISSING,
    GatewayClient,
    GatewayRefused,
    GatewayReplySender,
    GatewayToolExecutor,
    RunContext,
)
from ops_agents.activities.tool_directory import OperationRef
from ops_agents.store.tenancy import tenant_scope
from ops_identity import ServiceClient, dev_service_signer

from ..unit.test_tool_directory import Clock, Tools, directory, op
from .conftest import Gateway

DOC = {"customerId": "C-1042", "document": "proof of address", "reason": "Address changed last week."}


def executor(gateway: Gateway) -> GatewayToolExecutor:
    return GatewayToolExecutor(
        GatewayClient(ServiceClient(gateway.client, dev_service_signer(), "agents", "tools", tenant=lambda: "local"))
    )


async def test_a_read_runs_through_the_gateway_and_is_logged(gateway: Gateway) -> None:
    RUN_CONTEXT.set(RunContext(thread=gateway.thread))
    out = await executor(gateway).execute("lookup_account", {"query": "CHQ-2219"}, key="k1", approval_token=None)
    assert out.ok, out.output
    rows = await gateway.log.for_thread(gateway.thread, tenant_id="local")
    assert [(r["tool"], r["access"], r["decision"]) for r in rows] == [("lookup_account", "read", "allow")]


class KeptList:
    """A directory whose kept list may predate the team turning approvals on."""

    def __init__(self) -> None:
        self.forgotten = 0

    async def operations(self) -> list[OperationRef]:
        return []

    def forget(self) -> None:
        self.forgotten += 1


async def test_a_write_the_turn_thought_free_is_held_for_approval_not_refused_in_token_words(gateway: Gateway) -> None:
    """Approvals turned on after the turn read its tool list: the gateway wants a token the turn never asked for. The
    turn pauses for approval in plain words, and the kept list is dropped so the next turn reads the new answer."""
    RUN_CONTEXT.set(RunContext(thread=gateway.thread))
    kept = KeptList()
    client = GatewayClient(
        ServiceClient(gateway.client, dev_service_signer(), "agents", "tools", tenant=lambda: "local")
    )
    out = await GatewayToolExecutor(client, kept).execute("request_document", DOC, key="k2", approval_token=None)
    assert not out.ok
    assert out.needs_review and "token" not in out.needs_review, out
    assert "token" not in str(out.output), out.output
    assert kept.forgotten == 1, "the stale tool list must be dropped"


class FakeGateway:
    """The tools gateway at its edge, refusing a tokenless write with the given reasons."""

    def __init__(self, *reasons: str) -> None:
        self.reasons = list(reasons)

    async def call(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> dict[str, Any]:
        raise GatewayRefused("refused", self.reasons, "gateway_refused")


async def run_refused(reasons: list[str]) -> tuple[Any, list[str]]:
    """Reads the worker's tool list, runs a tokenless write the gateway refuses with `reasons`, reads the list again."""
    tools = Tools({"local": [op("request_document", "write")]})
    worker = directory(tools, Clock())
    with tenant_scope("local"):
        await worker.operations()
        out = await GatewayToolExecutor(FakeGateway(*reasons), worker).execute(  # type: ignore[arg-type]
            "request_document", DOC, key="k", approval_token=None
        )
        await worker.operations()
    return out, tools.requests


async def test_a_held_write_makes_the_workers_own_tool_list_forget() -> None:
    """The worker's ToolsOperations is not reached by the team's policy event, so the refusal is what drops its list."""
    out, requests = await run_refused([TOKEN_MISSING])
    assert out.needs_review
    assert requests == ["local", "local"], "the list must be read again after the refusal"


async def test_a_write_with_no_approval_rule_is_not_held() -> None:
    """The gateway asks for a token only where the team's rule makes the write wait; any other refusal reaches the model
    as a refusal, and the kept list stays."""
    out, requests = await run_refused(["tool is not registered with the gateway"])
    assert not out.ok and out.needs_review is None, out
    assert requests == ["local"], "a refusal that is not about approval must not drop the list"


async def test_write_carries_thread_and_step_from_the_run(gateway: Gateway) -> None:
    RUN_CONTEXT.set(RunContext(thread=gateway.thread))
    token = gateway.token("request_document", DOC, step="k3", approvers=["dana@bank.test"])
    out = await executor(gateway).execute("request_document", DOC, key="k3", approval_token=token)
    assert out.ok, out.output
    rows = await gateway.log.for_thread(gateway.thread, tenant_id="local")
    assert [(r["step"], r["decision"]) for r in rows] == [("k3", "allow")]


async def test_graph_node_supplies_its_thread_without_the_port_carrying_it(gateway: Gateway) -> None:
    """Graph nodes call the executor through the kernel's port, which has no thread; the LangGraph config does."""
    sender = GatewayReplySender(
        GatewayClient(ServiceClient(gateway.client, dev_service_signer(), "agents", "tools", tenant=lambda: "local"))
    )
    reply = {"to": "ana@example.com", "subject": "Re: card dispute", "body": "We have opened a dispute."}
    token = gateway.token("send_reply", reply, step="REV-1:reply", approvers=["dana@bank.test"])

    class S(TypedDict, total=False):
        sent: str

    async def send(state: S) -> dict[str, Any]:
        return {"sent": await sender.send(key="REV-1:reply", approval_token=token, **reply)}

    g = StateGraph(S)
    g.add_node("send", send)
    g.add_edge(START, "send")
    g.add_edge("send", END)
    out = await g.compile().ainvoke({}, {"configurable": {"thread_id": gateway.thread}})
    # The provider received the mail under the call's key, once: the reply left, it was not only logged.
    [sent] = gateway.mail.sent.values()
    assert (sent.key, sent.to, sent.subject) == ("REV-1:reply", ("ana@example.com",), "Re: card dispute")
    assert out["sent"] == await gateway.mail.send(sent)
    rows = await gateway.log.for_thread(gateway.thread, tenant_id="local")
    assert [(r["tool"], r["step"], r["decision"]) for r in rows] == [("send_reply", "REV-1:reply", "allow")]
