"""A pause inside a helper or a handed-over turn, by the failure modes of the acceptance table
(docs/design/agents-v2/automatic-mode-and-loop-kinds.md, row 7, and "A pause in a turn that was handed to"): the
helper's pause is lost and the asking turn answers without it, and the answer after an approval is lost from the
history of the agent the conversation was handed to."""

from __future__ import annotations

from typing import Any, cast

from ops_agents.api.runs import config, pending, resolve
from ops_agents.store.tenancy import tenant_scope
from tests.api.test_action_roles import ADMIN, REVIEWER, VIEWER
from tests.api.test_team_default_agent import (
    URL,
    Stack,
    ask,
    say,
    stack,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    start,
)
from tests.engine.test_lifecycle_rights import TENANT

HOLD = "Place a 24-hour hold on wire W-88213"


async def _approve(c: Any, thread: str) -> None:
    up = await c.post("/v1/auth/step-up", json={"password": "northfield-demo"}, headers=REVIEWER)
    assert up.status_code == 200, up.text
    body = {"decision": "approved", "stepUpToken": up.json()["data"]["token"]}
    ran = await c.post(f"/reviews/{thread}/decision", json=body, headers=REVIEWER)
    assert ran.status_code == 200, ran.text


async def _values(rt: Any, thread: str) -> tuple[dict[str, Any], list[Any]]:
    _, graph = await resolve(rt, thread)
    snap = await graph.aget_state(config(thread))
    return dict(snap.values), pending(snap)


async def test_a_helpers_pause_pauses_the_asking_turn_and_its_approval_resumes_both(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    thread = (await start(c, VIEWER))["id"]
    await say(c, thread, ask("ag_fraud", HOLD), VIEWER)
    _, waiting = await _values(rt, thread)
    assert waiting, "the asking turn waits on the helper's review"
    nested = cast(dict[str, Any], cast(dict[str, Any], waiting[0]["payload"]).get("nested") or {})
    helper = str(nested.get("threadId") or "")
    assert helper and (await _values(rt, helper))[1], waiting[0]["payload"]
    listed = (await c.get("/reviews", params={"view": "open"}, headers=REVIEWER)).json()["data"]["data"]
    # The queue lists the write once, on the conversation the person asked in.
    assert [r["id"] for r in listed if r["id"] in (thread, helper)] == [thread], listed
    # Approved where the person is asked: on the asking thread, which hands the decision to the helper's write.
    await _approve(c, thread)
    assert not (await _values(rt, helper))[1], "the helper's write ran"
    after, still = await _values(rt, thread)
    assert not still, "the asking turn went on once the helper answered"
    results = cast(list[dict[str, Any]], after.get("tool_results") or [])
    answered = [r for r in results if r["tool"] == "agent__ag_fraud"]
    assert answered and answered[-1]["output"]["status"] == "answered", after.get("tool_results")
    assert rt.graph_store is not None
    with tenant_scope(TENANT):
        children = [t for t in await rt.graph_store.thread_rows("agent_wrapper") if t.parent_thread_id == thread]
    assert len(children) == 1, "one helper thread for the one call"


async def test_an_approval_in_a_handed_over_turn_answers_from_the_agent_handed_to(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    at = next(i for i, a in enumerate(rt.catalog.agents) if a.id == "ag_branch")
    rt.catalog.agents[at] = rt.catalog.agents[at].model_copy(
        update={"loop": {"kind": "swarm"}, "handoffs": ["ag_fraud"]}
    )
    thread = (await start(c, VIEWER))["id"]
    await say(c, thread, f'call hand_over {{"agentId": "ag_fraud", "message": "{HOLD}"}}', VIEWER)
    before, waiting = await _values(rt, thread)
    assert waiting and before["active_agent"] == "ag_fraud", before.get("reply")
    await _approve(c, thread)
    after, still = await _values(rt, thread)
    assert not still and after["reply"], after.get("reply")
    own = after["loop_states"]["ag_fraud"]
    assert own[-1] == {"role": "assistant", "content": after["reply"]}, own
