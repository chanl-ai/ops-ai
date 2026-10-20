"""A chat conversation's budget (c-103), by failure mode: a chat with no ceiling; a spent budget drawn as an approval
or leaving the chat stuck; numbers that are not the server's ledger; someone other than the owner continuing, or a
non-admin raising; Continue or Raise not resuming the paused turn; the run API answering a chat's pause without those
checks; a run-API agent thread with no budget or a caller's higher one; two answers at once, or a stale tab, both
recorded; a raise that leaves the paused cap where it was; a new cost cap printed with six places."""

from __future__ import annotations

from typing import Any, cast

import pytest
from httpx import AsyncClient

from ops_agents.api import chat_threads
from ops_agents.api.agent_registry import PLATFORM_CONVERSATION_CALLS
from ops_agents.api.deps import Runtime
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_metering import Budget
from ops_policy import mint
from tests.api.test_write_approval_policy import (
    PLATFORM,
    dev_platform,  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixture
)

LOOKUP = "Look up CHQ-2219"


def who(sub: str, role: str) -> dict[str, str]:
    claims = {
        "sub": sub,
        "email": f"{sub}@northfield.example",
        "name": sub,
        "kind": "person",
        "aud": ["agents"],
        "tenant_id": "acme",
        "team_ids": ["team_ops"],
        "roles": {"team_ops": role},
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": "team_ops"}


OWNER, ADMIN, OTHER = who("usr_owner", "builder"), who("usr_admin", "admin"), who("usr_other", "builder")
VIEWER = who("usr_viewer", "viewer")


def rt_of(client: AsyncClient) -> Runtime:
    return client._transport.app.state.runtime  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType, reportPrivateUsage]


async def paused(client: AsyncClient) -> tuple[str, dict[str, Any]]:
    """A conversation whose one-call budget is spent: the budget is checked as each turn starts, so the first turn
    (a tool call and an answer) finishes over it and the second pauses before calling the model."""
    made = await client.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": []}, headers=OWNER)
    assert made.status_code == 201, made.text
    tid = made.json()["data"]["id"]
    rt = rt_of(client)
    assert rt.usage is not None
    await rt.usage.set_budget(tid, Budget(max_calls=1))
    sent = await client.post(
        f"/chat/threads/{tid}/messages", json={"content": LOOKUP}, headers={**OWNER, "Accept": "text/event-stream"}
    )
    assert sent.status_code == 200, sent.text
    second = await client.post(
        f"/chat/threads/{tid}/messages",
        json={"content": "And the hold?"},
        headers={**OWNER, "Accept": "text/event-stream"},
    )
    assert second.status_code == 200, second.text
    thread = (await client.get(f"/chat/threads/{tid}", headers=OWNER)).json()["data"]
    return tid, thread


async def test_a_chat_starts_with_the_agents_conversation_caps(dev_platform: AsyncClient) -> None:  # noqa: F811
    made = await dev_platform.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": []}, headers=OWNER)
    rt = rt_of(dev_platform)
    assert rt.usage is not None
    budget = await rt.usage.budget(made.json()["data"]["id"])
    assert budget is not None and budget.max_calls == PLATFORM_CONVERSATION_CALLS and budget.max_cost is not None


async def test_a_spent_budget_is_a_budget_card_with_the_ledgers_numbers(dev_platform: AsyncClient) -> None:  # noqa: F811
    tid, thread = await paused(dev_platform)
    reply = thread["messages"][-1]
    rt = rt_of(dev_platform)
    assert rt.usage is not None
    spent = await rt.usage.totals(tid)
    budget = dict(reply.get("budget") or {})
    assert budget.pop("id"), "the pause carries its interrupt id"
    assert budget == {"limit": "calls", "spent": str(spent.calls), "cap": "1", "state": "waiting"}, reply
    assert not reply.get("widgets"), "a budget pause is never drawn as an approval"
    again = await dev_platform.post(
        f"/chat/threads/{tid}/messages", json={"content": "hello"}, headers={**OWNER, "Accept": "text/event-stream"}
    )
    assert again.status_code == 409 and again.json()["error"]["code"] == "budget_paused"


async def test_only_the_owner_continues_and_continue_finishes_the_turn(dev_platform: AsyncClient) -> None:  # noqa: F811
    tid, _ = await paused(dev_platform)
    refused = await dev_platform.post(f"/chat/threads/{tid}/budget", json={"action": "continue"}, headers=OTHER)
    assert refused.status_code == 403, refused.text
    done = await dev_platform.post(f"/chat/threads/{tid}/budget", json={"action": "continue"}, headers=OWNER)
    assert done.status_code == 200, done.text
    messages = done.json()["data"]["messages"]
    card = next(m for m in messages if m.get("budget"))
    assert card["budget"]["state"] == "continued" and card["budget"]["answeredBy"] == "usr_owner@northfield.example"
    assert any(
        m["role"] == "assistant" and m["content"] and not m.get("budget") for m in messages[messages.index(card) :]
    ), "the paused turn answered after Continue"
    rt = rt_of(dev_platform)
    assert rt.usage is not None
    budget = await rt.usage.budget(tid)
    assert budget is not None and budget.max_calls is not None and budget.max_calls > 1


@pytest.mark.parametrize("person", [OWNER, OTHER])
async def test_only_a_team_admin_raises(dev_platform: AsyncClient, person: dict[str, str]) -> None:  # noqa: F811
    tid, _ = await paused(dev_platform)
    refused = await dev_platform.post(
        f"/chat/threads/{tid}/budget", json={"action": "raise", "maxCalls": 10}, headers=person
    )
    assert refused.status_code == 403, refused.text
    too_low = await dev_platform.post(
        f"/chat/threads/{tid}/budget", json={"action": "raise", "maxCalls": 1}, headers=ADMIN
    )
    assert too_low.status_code == 422, too_low.text
    raised = await dev_platform.post(
        f"/chat/threads/{tid}/budget", json={"action": "raise", "maxCalls": 10}, headers=ADMIN
    )
    assert raised.status_code == 200, raised.text
    rt = rt_of(dev_platform)
    assert rt.usage is not None
    budget = await rt.usage.budget(tid)
    assert budget is not None and budget.max_calls == 10
    card = next(m for m in raised.json()["data"]["messages"] if m.get("budget"))
    assert card["budget"]["state"] == "raised" and card["budget"]["newCap"] == "10"


async def test_the_run_api_never_answers_a_chats_budget_pause(dev_platform: AsyncClient) -> None:  # noqa: F811
    tid, _ = await paused(dev_platform)
    url = f"/v1/threads/{tid}/runs/stream"
    raised = await dev_platform.post(
        url, json={"resume": {"decision": "approved", "budget": {"maxCalls": 100000}}}, headers=VIEWER
    )
    ended = await dev_platform.post(url, json={"resume": {"decision": "rejected"}}, headers=OTHER)
    for res in (raised, ended):
        assert res.status_code == 409 and res.json()["error"]["code"] == "resume_via_budget", res.text
    rt = rt_of(dev_platform)
    assert rt.usage is not None
    budget = await rt.usage.budget(tid)
    assert budget is not None and budget.max_calls == 1


async def test_a_run_api_agent_thread_takes_the_agents_caps_or_a_lower_one(dev_platform: AsyncClient) -> None:  # noqa: F811
    rt = rt_of(dev_platform)
    assert rt.usage is not None
    caps: list[int | None] = []
    for asked in (None, {"maxCalls": 100000}, {"maxCalls": 3}):
        body: dict[str, Any] = {"graph": "agent:ag_fraud", **({"budget": asked} if asked else {})}
        made = await dev_platform.post("/v1/threads", json=body, headers=ADMIN)
        assert made.status_code == 201, made.text
        tid = made.json()["data"]["threadId"]
        await dev_platform.post(f"/v1/threads/{tid}/runs/stream", json={"input": {"message": "hi"}}, headers=ADMIN)
        budget = await rt.usage.budget(tid)
        caps.append(budget.max_calls if budget else None)
    assert caps == [PLATFORM_CONVERSATION_CALLS, PLATFORM_CONVERSATION_CALLS, 3]


async def test_an_answer_needs_the_lease_and_the_current_pause(dev_platform: AsyncClient) -> None:  # noqa: F811
    tid, thread = await paused(dev_platform)
    pause_id = thread["messages"][-1]["budget"]["id"]
    url = f"/chat/threads/{tid}/budget"
    stale = await dev_platform.post(url, json={"action": "continue", "pauseId": "int_older"}, headers=OWNER)
    rt = rt_of(dev_platform)
    assert rt.leases is not None
    await rt.leases.acquire(tid, "run_elsewhere")
    busy = await dev_platform.post(url, json={"action": "continue", "pauseId": pause_id}, headers=OWNER)
    await rt.leases.release(tid, "run_elsewhere")
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_pause", stale.text
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "run_active", busy.text
    after = (await dev_platform.get(f"/chat/threads/{tid}", headers=OWNER)).json()["data"]["messages"][-1]["budget"]
    assert after["state"] == "waiting", "an answer that did not run records nothing"
    went = await dev_platform.post(url, json={"action": "continue", "pauseId": pause_id}, headers=OWNER)
    assert went.status_code == 200, went.text


async def test_a_raise_lifts_the_cap_that_paused_the_turn(dev_platform: AsyncClient) -> None:  # noqa: F811
    tid, _ = await paused(dev_platform)
    wrong = await dev_platform.post(
        f"/chat/threads/{tid}/budget", json={"action": "raise", "maxCost": 9}, headers=ADMIN
    )
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "cap_required", wrong.text


def test_a_new_cost_cap_reads_like_the_cap_it_replaces() -> None:
    assert chat_threads._like("5.00", "7.500000") == "7.50"  # pyright: ignore[reportPrivateUsage]


async def test_a_run_api_thread_answers_its_budget_pause_by_the_chats_rules(dev_platform: AsyncClient) -> None:  # noqa: F811
    made = await dev_platform.post(
        "/v1/threads", json={"graph": "agent:ag_fraud", "budget": {"maxCalls": 1}}, headers=OWNER
    )
    tid = made.json()["data"]["threadId"]
    url = f"/v1/threads/{tid}/runs/stream"
    for message in (LOOKUP, "And the hold?"):
        await dev_platform.post(url, json={"input": {"message": message}}, headers=OWNER)
    state = (await dev_platform.get(f"/v1/threads/{tid}/state", headers=OWNER)).json()["data"]
    assert state["interrupt"]["payload"]["kind"] == "budget_exhausted", state
    raise_ = {"resume": {"decision": "approved", "budget": {"maxCalls": 100000}}}
    owner_raises = await dev_platform.post(url, json=raise_, headers=OWNER)
    other_continues = await dev_platform.post(url, json={"resume": {"decision": "approved"}}, headers=OTHER)
    too_low = await dev_platform.post(
        url, json={"resume": {"decision": "approved", "budget": {"maxCalls": 1}}}, headers=ADMIN
    )
    assert owner_raises.status_code == 403 and owner_raises.json()["error"]["code"] == "admin_only", owner_raises.text
    assert other_continues.status_code == 403 and other_continues.json()["error"]["code"] == "not_owner"
    assert too_low.status_code == 422 and too_low.json()["error"]["code"] == "cap_too_low", too_low.text
    went = await dev_platform.post(url, json={"resume": {"decision": "approved"}}, headers=OWNER)
    assert went.status_code == 200, went.text
    rt = rt_of(dev_platform)
    assert rt.usage is not None
    budget, spent = await rt.usage.budget(tid), await rt.usage.totals(tid)
    assert budget is not None and budget.max_calls is not None
    assert budget.max_calls <= spent.calls + PLATFORM_CONVERSATION_CALLS, "a continue adds one allotment, no more"


FORGED = {"budgetAllotment": {"maxCalls": 100000, "maxCost": "100000"}, "ownerEmail": "someone@else.example"}


async def test_a_caller_cannot_forge_a_threads_allotment_or_owner(dev_platform: AsyncClient) -> None:  # noqa: F811
    rt = rt_of(dev_platform)
    assert rt.usage is not None
    caps: list[int | None] = []
    for asked in ({"maxCalls": 100000}, None):
        body: dict[str, Any] = {"graph": "agent:ag_fraud", "metadata": FORGED, **({"budget": asked} if asked else {})}
        made = await dev_platform.post("/v1/threads", json=body, headers=OWNER)
        assert made.status_code == 201, made.text
        tid = made.json()["data"]["threadId"]
        budget = await rt.usage.budget(tid)
        caps.append(budget.max_calls if budget else None)
        assert rt.graph_store is not None
        row = await rt.graph_store.thread(tid)
        assert row is not None
        meta = cast(dict[str, Any], row["meta"])
        assert meta["ownerEmail"] == "usr_owner@northfield.example", meta
        assert meta["budgetAllotment"]["maxCalls"] == PLATFORM_CONVERSATION_CALLS, meta
    assert caps == [PLATFORM_CONVERSATION_CALLS, PLATFORM_CONVERSATION_CALLS]


async def test_a_continue_adds_the_agents_allotment_not_a_forged_one(dev_platform: AsyncClient) -> None:  # noqa: F811
    body = {"graph": "agent:ag_fraud", "budget": {"maxCalls": 1}, "metadata": FORGED}
    tid = (await dev_platform.post("/v1/threads", json=body, headers=OWNER)).json()["data"]["threadId"]
    url = f"/v1/threads/{tid}/runs/stream"
    for message in (LOOKUP, "And the hold?"):
        await dev_platform.post(url, json={"input": {"message": message}}, headers=OWNER)
    went = await dev_platform.post(url, json={"resume": {"decision": "approved"}}, headers=OWNER)
    assert went.status_code == 200, went.text
    rt = rt_of(dev_platform)
    assert rt.usage is not None
    budget, spent = await rt.usage.budget(tid), await rt.usage.totals(tid)
    assert budget is not None and budget.max_calls is not None
    assert budget.max_calls <= spent.calls + PLATFORM_CONVERSATION_CALLS, budget
