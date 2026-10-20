"""The runner's tool port on the gateway client: a call carries the run's thread, key and lease generation as v1
calls do, a refusal is the refused port and not a retry, and a write is reconciled from the call log by its key."""

from __future__ import annotations

import json
from typing import Any, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph  # pyright: ignore[reportMissingTypeStubs]

from ops_agents.activities.gateway import GatewayClient, acting_as
from ops_agents.api.engine_host import GatewayTools
from ops_agents.graphs.agent_wrapper import turn_environment
from ops_identity import ServiceClient, dev_service_signer

KEY = "wfrun_abc:hold:1:1"


def tools(handler: Any) -> GatewayTools:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://tools")
    return GatewayTools(
        GatewayClient(ServiceClient(client, dev_service_signer(), "agents", "tools", tenant=lambda: "local"))
    )


async def test_a_call_carries_the_runs_thread_key_and_generation() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"success": True, "data": {"ok": True, "output": {"ref": "H-1"}}})

    result = await tools(handler).call("place_hold", {"amount": 5}, KEY, 3, None)
    body = json.loads(seen[0].content)
    assert result.ok and result.output == {"ref": "H-1"}
    assert seen[0].headers["X-Lease-Generation"] == "3"
    assert (body["key"], body["runContext"]["thread"], body["runContext"]["step"]) == (KEY, "wfrun_abc", KEY)


async def test_a_refusal_is_the_refused_port() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        err = {"code": "forbidden", "message": "no token", "details": {"reasons": ["approval required"]}}
        return httpx.Response(403, json={"success": False, "error": err})

    result = await tools(handler).call("place_hold", {}, KEY, 1, None)
    assert (result.ok, result.refused) == (False, True)


def abandoning(answers: dict[str, dict[str, Any]], seen: list[dict[str, Any]]) -> Any:
    """The gateway's POST /v1/calls/abandon: the call under a key, or the key abandoned."""

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append(body)
        call = answers.get(body["key"])
        data = {"abandoned": call is None, "call": call}
        return httpx.Response(200, json={"success": True, "data": data})

    return handler


async def test_a_write_is_decided_on_its_claim_or_abandoned_when_absent() -> None:
    seen: list[dict[str, Any]] = []
    answers = {KEY: {"id": "call_1", "outcome": "ok", "effect": True, "decision": "allow"}}
    port = tools(abandoning(answers, seen))
    found = await port.find(KEY, "place_hold")
    assert found is not None and found.ok and found.output["callId"] == "call_1"
    assert await port.find("wfrun_abc:hold:1:2", "place_hold") is None
    assert seen[-1] == {"key": "wfrun_abc:hold:1:2", "tool": "place_hold", "thread": "wfrun_abc"}


async def test_a_claim_still_running_is_pending_and_a_lost_one_is_an_error() -> None:
    answers = {
        KEY: {"id": "c1", "outcome": "running", "effect": True, "decision": "allow"},
        "wfrun_abc:hold:1:3": {"id": "c3", "outcome": "lost", "effect": True, "decision": "allow"},
        "wfrun_abc:hold:1:4": {"id": "c4", "outcome": "refused", "effect": False, "decision": "deny"},
    }
    port = tools(abandoning(answers, []))
    running = await port.find(KEY, "place_hold")
    assert running is not None and running.pending and not running.ok
    lost = await port.find("wfrun_abc:hold:1:3", "place_hold")
    assert lost is not None and not lost.ok and not lost.pending and "lost" in str(lost.reason)
    refused = await port.find("wfrun_abc:hold:1:4", "place_hold")
    assert refused is not None and refused.refused


async def _environment_sent(mode: str | None) -> str | None:
    """What a call made inside a graph run in `mode` (the engine's `engine_mode`) names as its environment."""
    seen: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"success": True, "data": {"ok": True, "output": {}}})

    port = tools(handler)

    class State(TypedDict):
        done: bool

    async def step(_: State) -> State:
        await port.call("get_account", {}, KEY, 1, None)
        return {"done": True}

    graph: Any = StateGraph(State)
    graph.add_node("step", step)
    graph.add_edge(START, "step")
    graph.add_edge("step", END)
    configurable = {"thread_id": "wfrun_abc", **({"engine_mode": mode} if mode else {})}
    await graph.compile().ainvoke({"done": False}, {"configurable": configurable})
    return seen[0]["runContext"].get("environment")


async def test_a_test_run_calls_in_test_and_a_live_run_in_production() -> None:
    """c-330: the gateway picks a connection's settings by this; a run that names no mode leaves it to the gateway."""
    assert await _environment_sent("test") == "test"
    assert await _environment_sent("live") == "production"
    assert await _environment_sent(None) is None


async def test_a_test_chat_calls_in_test_and_a_live_chat_in_production() -> None:
    """c-330/c-332: an agent turn names its environment, so a test chat's tool call reaches its mock and a live chat's
    never does; the test chat is the thread whose state carries the agent under test."""
    seen: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"success": True, "data": {"ok": True, "output": {}}})

    client = tools(handler)._gw()  # pyright: ignore[reportPrivateUsage]
    for state in ({"test_agent": {"id": "ag_x"}}, {}):
        with acting_as("agent:ag_x", turn_environment(state)):
            await client.call("get_account", {}, key="k", approval_token=None)
    assert [s["runContext"]["environment"] for s in seen] == ["test", "production"]
