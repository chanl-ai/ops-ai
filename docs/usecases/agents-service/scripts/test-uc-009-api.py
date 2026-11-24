"""uc-009 self-approval is refused, api layer: docs/usecases/agents-service/self-approval-refused.md.

Two stacks, one after the other. The chat: the fraud agent drafts a hold and its asker may not approve it. The
workflow: real tools-service, platform-service and an engine worker, with platform sign-in, decide whether a run's
starter approves their own write, asked live of platform-service's access check at the review step (agents-service)
and again where the write is sent (tools-service). No model call is made in the workflow part."""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any

import httpx
from usecase_harness import (
    AGENTS_PORT,
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    TOOLS_PORT,
    agents,
    bearer,
    check,
    data,
    engine_worker,
    finish,
    platform,
    signed_in,
    sse,
    tools,
    until,
)

# Platform sign-in, so each person carries their roles: the dev header caller holds every cell and would decide its own
# request. James is a Builder, whose role lacks Approvals · decide; Priya is the team's Admin, whose role has it.
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
JAMES, PRIYA = "j.richardson@harborpine.example", "p.shah@harborpine.example"
# The workspace admin (Admin in every team), who makes and edits roles.
WANJIRU = "w.kamau@harborpine.example"


with platform() as (people, _internal), agents(env=AUTH) as api:
    james = bearer(signed_in(people, JAMES), "team_ops")
    priya = bearer(signed_in(people, PRIYA), "team_ops")
    thread = data(api.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": []}, headers=james))
    res = api.post(
        f"/chat/threads/{thread['id']}/messages",
        json={"content": "Place a 24-hour hold on wire W-88213"},
        headers={**james, "Accept": "text/event-stream"},
    )
    events = sse(res.text)
    widget = next((e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval"), None)
    check("James's request paused on an approval", widget is not None, [e["type"] for e in events])
    assert widget is not None
    url = f"/chat/threads/{thread['id']}/messages/{events[0]['messageId']}/widgets/{widget['id']}/actions"

    def step_up(who: dict[str, str]) -> str:
        return data(api.post("/v1/auth/step-up", json={"password": "northfield-demo"}, headers=who))["token"]

    own = api.post(url, json={"type": "approve", "stepUpToken": step_up(james)}, headers=james)
    message = (own.json().get("error") or {}).get("message", "")
    check("James approving his own request is refused (403)", own.status_code == 403, own.text[:200])
    check("the refusal says someone else must decide", "someone else" in message, message)
    # Non-vacuous pair: the same approval by another person goes through, so the 403 above is about who, not what.
    other = api.post(url, json={"type": "approve", "stepUpToken": step_up(priya)}, headers=priya)
    check(
        "Priya approving it succeeds (200)",
        other.status_code == 200 and data(other)["state"] == "approved",
        other.text[:200],
    )


def definition(wid: str, *, hold: bool) -> str:
    """A fee waiver whose write waits on a review; with `hold`, a second look by someone else sits between the review's
    approval and the send, so a cell unticked there is read only where the write is sent."""
    after_review = "hold" if hold else "waive"
    hold_node = (
        "  - {id: hold, type: ops.flow.humanReview, typeVersion: 1, name: Second look, parameters: {title: Second look}}\n"
        if hold
        else ""
    )
    hold_edge = (
        "  - {from: {node: hold, port: approve}, to: {node: waive, port: in}}\n"
        "  - {from: {node: hold, port: reject}, to: {node: declined, port: in}}\n"
        if hold
        else ""
    )
    return f"""
schemaVersion: 2
id: {wid}
name: Fee waiver ({wid})
nodes:
  - {{id: start, type: ops.trigger.request, typeVersion: 1, name: Request}}
  - id: review
    type: ops.flow.humanReview
    typeVersion: 1
    name: Approve waiving the fee
    parameters: {{title: "Waive {{$.input.amount}}", approves: waive}}
{hold_node}  - id: waive
    type: ops.action.tool
    typeVersion: 1
    name: Waive the fee
    parameters:
      operation: waive_fee
      approvedBy: review
      input: {{cardAccount: "$.input.cardAccount", feeId: "$.input.feeId", amount: "$.input.amount"}}
  - {{id: done, type: ops.flow.end, typeVersion: 1, name: Waived, parameters: {{outcome: waived}}}}
  - {{id: declined, type: ops.flow.end, typeVersion: 1, name: Declined, parameters: {{outcome: declined}}}}
  - id: failed
    type: ops.flow.end
    typeVersion: 1
    name: Could not finish
    parameters: {{outcome: failed, result: failed}}
connections:
  - {{from: {{node: start, port: payload}}, to: {{node: review, port: in}}}}
  - {{from: {{node: review, port: approve}}, to: {{node: {after_review}, port: in}}}}
  - {{from: {{node: review, port: reject}}, to: {{node: declined, port: in}}}}
{hold_edge}  - {{from: {{node: waive, port: ok}}, to: {{node: done, port: in}}}}
  - {{from: {{node: waive, port: refused}}, to: {{node: failed, port: in}}}}
  - {{from: {{node: waive, port: error}}, to: {{node: failed, port: in}}}}
"""


FEE: dict[str, Any] = {"cardAccount": "CARD-4471", "feeId": "FEE-3901", "amount": 35}


def run_of(api: httpx.Client, run_id: str, who: dict[str, str]) -> dict[str, Any]:
    return data(api.get(f"/v1/runs/{run_id}", headers=who)) or {}


def step(run: dict[str, Any], node: str) -> dict[str, Any]:
    return next((s for s in reversed(run.get("steps") or []) if s.get("nodeId") == node), {})


def start(api: httpx.Client, wid: str, key: str, who: dict[str, str]) -> str:
    started = api.post("/v1/runs", json={"workflowId": wid, "input": FEE, "runKey": key}, headers=who)
    return str((data(started) or {}).get("runId") or started.text[:200])


def settled(api: httpx.Client, run_id: str, who: dict[str, str], *statuses: str) -> dict[str, Any]:
    return until(lambda: (r := run_of(api, run_id, who)).get("status") in statuses and r) or run_of(api, run_id, who)


with ExitStack() as stack:
    people, _internal = stack.enter_context(platform())
    james = bearer(signed_in(people, JAMES), "team_ops")
    priya = bearer(signed_in(people, PRIYA), "team_ops")
    wanjiru = bearer(signed_in(people, WANJIRU), "team_ops")
    # tools-service on platform sign-in too, so it takes the acting-for tokens platform-service mints for the worker.
    stack.enter_context(tools({"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"} | AUTH))
    api = stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}", env=AUTH))
    # The team's writes wait for a reviewer, as Govern > Approvals saves it: only then does a write carry an approval
    # that tools-service asks about again where it sends it.
    asks = people.put(
        "/v1/policies/appChanges",
        json={"value": {"ask": True, "answer": "reviewer", "reviewerRole": "reviewer", "testAccountsNeverAsk": False}},
        headers=priya,
    )
    check("4 Priya turns on asking a reviewer before the team's writes", asks.status_code == 200, asks.text[:200])
    james = bearer(signed_in(people, JAMES), "team_ops")
    priya = bearer(signed_in(people, PRIYA), "team_ops")
    for wid, hold in (("uc009_waiver", False), ("uc009_waiver_held", True)):
        created = api.post("/v1/workflows/definitions", json={"yaml": definition(wid, hold=hold)}, headers=priya)
        live = api.post(f"/v1/workflows/definitions/{wid}/publish-requests", json={}, headers=priya)
        check(
            f"4 the {wid} workflow saves and goes live",
            created.status_code == 201 and (data(live) or {}).get("status") == "approved",
            created.text[:300] + live.text[:200],
        )
    stack.enter_context(engine_worker("uc009", {"OPS_GATEWAY_URL": f"http://127.0.0.1:{TOOLS_PORT}"} | AUTH))

    # A Builder's own write waits for someone else.
    built = start(api, "uc009_waiver", "uc009-james", james)
    waiting = settled(api, built, james, "waiting", "succeeded", "failed")
    review = step(waiting, "review")
    check(
        "5 James (Builder) starts a run: its write waits on someone else",
        waiting.get("status") == "waiting" and review.get("status") in ("waiting", "running") and not step(waiting, "waive"),
        {"status": waiting.get("status"), "review": review},
    )
    review_id = f"{built}:review:{review.get('iteration', 0)}"
    own = api.post(f"/reviews/{review_id}/decision", json={"decision": "approved", "reason": "uc-009"}, headers=james)
    check("6 James approving his own run's write is refused (403)", own.status_code == 403, own.text[:200])

    # An Admin's own write is sent without a second person.
    admin = start(api, "uc009_waiver", "uc009-priya", priya)
    sent = settled(api, admin, priya, "succeeded", "failed", "waiting")
    decided = step(sent, "review").get("output") or {}
    check(
        "7 Priya (Admin) starts a run: the review is decided as hers and the write is sent",
        sent.get("status") == "succeeded"
        and (step(sent, "waive").get("output") or {}).get("code") != "own_request"
        and decided.get("decision") == "approve",
        {"status": sent.get("status"), "review": decided, "waive": step(sent, "waive")},
    )

    # A custom role ticked with Approve own requests; unticking it while the run waits refuses the send.
    made = people.post(
        "/v1/roles",
        json={
            "name": "Loan officer",
            "permissions": [
                {"area": "approvals", "action": "view", "scope": "all"},
                {"area": "approvals", "action": "decide", "scope": "all"},
            ],
        },
        headers=wanjiru,
    )
    role = data(made) or {}
    options = data(people.get(f"/v1/roles/{role.get('id')}/holder-options?search=James", headers=wanjiru)) or {}
    person = next((str(o["id"]) for o in options.get("data") or [] if str(o.get("id", "")).startswith("person:")), "")
    given = people.post(
        f"/v1/roles/{role.get('id')}/holders", json={"kind": "person", "id": person.split(":", 1)[-1]}, headers=wanjiru
    )
    check(
        "8 the workspace admin makes a Loan officer role with Approve own requests and gives it to James in the team",
        made.status_code == 201 and given.status_code == 201,
        {"made": made.text[:300], "person": person, "given": given.text[:200]},
    )
    # A role change raises the workspace's permission version, so earlier tokens are refused until signed in again.
    james = bearer(signed_in(people, JAMES), "team_ops")
    held = start(api, "uc009_waiver_held", "uc009-loan-officer", james)
    at_hold = until(lambda: (r := run_of(api, held, james)).get("status") == "waiting" and step(r, "hold") and r) or {}
    own_review = step(at_hold, "review").get("output") or {}
    check(
        "9 as a Loan officer James's own review is decided as his, and the run waits on the second look",
        own_review.get("decision") == "approve" and bool(step(at_hold, "hold")),
        {"status": at_hold.get("status"), "review": own_review, "hold": step(at_hold, "hold")},
    )
    unticked = people.put(
        f"/v1/roles/{role.get('id')}/permissions",
        json={"permissions": [{"area": "approvals", "action": "view", "scope": "all"}]},
        headers=wanjiru,
    )
    priya = bearer(signed_in(people, PRIYA), "team_ops")
    hold_id = f"{held}:hold:{step(at_hold, 'hold').get('iteration', 0)}"
    looked = api.post(f"/reviews/{hold_id}/decision", json={"decision": "approved", "reason": "uc-009"}, headers=priya)
    ended = settled(api, held, priya, "succeeded", "failed")
    waive = step(ended, "waive")
    said = str(waive.get("output") or waive.get("error") or "")
    check(
        "10 the cell is unticked while the run waits, Priya approves the second look; the write's send is refused with own_request",
        unticked.status_code == 200
        and looked.status_code == 200
        and ended.get("status") in ("succeeded", "failed")
        and waive.get("port") == "refused"
        and ("own_request" in said or "someone else has to decide" in said),
        {"untick": unticked.status_code, "hold": looked.text[:200], "status": ended.get("status"), "waive": waive},
    )

finish()
