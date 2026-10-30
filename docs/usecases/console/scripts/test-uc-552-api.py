"""uc-552 Overview's lists in one call, api layer: docs/usecases/console/chat-first.md. The agents service and a real
worker: a run waits on a person and its Human Task is assigned to Maya; cases are due, late, later, resolved and paused.
One GET /v1/overview answers what the sidebar count, the Overview widgets and Chat's hints read, already joined, and
its count agrees with Human Tasks' Assigned to me. No model call is made."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime, timedelta

from usecase_harness import TEAM, agents, check, data, engine_worker, finish, until

DEFINITION = """
schemaVersion: 2
id: uc552_refund
name: Refund over 100 (uc-552)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}
  - id: review
    type: ops.flow.humanReview
    typeVersion: 1
    name: Refund over 100
    parameters: {title: Refund over 100}
  - {id: approved, type: ops.flow.end, typeVersion: 1, name: Approved, parameters: {outcome: approved}}
  - {id: rejected, type: ops.flow.end, typeVersion: 1, name: Rejected, parameters: {outcome: rejected}}
connections:
  - {from: {node: start, port: payload}, to: {node: review, port: in}}
  - {from: {node: review, port: approve}, to: {node: approved, port: in}}
  - {from: {node: review, port: reject}, to: {node: rejected, port: in}}
"""
MAYA = {**TEAM, "X-Dev-User": "m.okafor@harborpine.example"}
PAST = "2020-01-01T00:00:00.000Z"


def soon(**delta: float) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


with ExitStack() as stack:
    api = stack.enter_context(agents())
    created = api.post("/v1/workflows/definitions", json={"yaml": DEFINITION}, headers=TEAM)
    live = api.post("/v1/workflows/definitions/uc552_refund/publish-requests", json={}, headers=TEAM)
    check(
        "0 the workflow saves and goes live",
        created.status_code == 201 and data(live)["status"] == "approved",
        live.text[:200],
    )
    stack.enter_context(engine_worker("uc552"))

    runs = [
        str(data(api.post("/v1/runs", json={"workflowId": "uc552_refund", "input": {"n": i}}, headers=TEAM))["runId"])
        for i in (1, 2)
    ]
    reviews = [f"{r}:review:1" for r in runs]
    waiting = until(
        lambda: (
            all((data(api.get(f"/v1/runs/{r}", headers=TEAM)) or {}).get("status") == "waiting" for r in runs) or None
        )
    )
    assigned = data(api.post("/reviews/assign", json={"ids": reviews, "assignee": MAYA["X-Dev-User"]}, headers=MAYA))
    check(
        "0 both runs wait on a person and Maya holds their tasks",
        bool(waiting) and assigned["updated"] == reviews,
        assigned,
    )

    def case(subject: str, **patch: str) -> str:
        made = data(api.post("/v1/cases", json={"subject": subject}, headers=TEAM))
        if patch:
            data(api.patch(f"/v1/cases/{made['id']}", json=patch, headers=TEAM))
        return str(made["id"])

    late = case("Late case", resolutionDueAt=PAST)
    today = case("Due shortly", resolutionDueAt=soon(minutes=1))
    later = case("Due next week", resolutionDueAt=soon(days=7))
    done = case("Resolved", status="resolved", resolutionDueAt=PAST)
    paused = case("Waiting on the customer", status="waiting_on_customer", resolutionDueAt=PAST)

    o = data(api.get("/v1/overview", headers=MAYA))
    check(
        "1 Maya's tasks are listed for her, the one waiting longest first",
        [r["id"] for r in o["waitingForMe"]] == reviews,
        o["waitingForMe"],
    )
    mine = data(api.get("/reviews", params={"view": "mine", "pageSize": 1}, headers=MAYA))["viewCounts"]["mine"]
    check(
        "1 her count equals Human Tasks' Assigned to me", o["counts"]["waitingForMe"] == mine == 2, (o["counts"], mine)
    )
    james = data(api.get("/v1/overview", headers=TEAM))
    check(
        "2 a task assigned to Maya is not waiting for anyone else",
        not {r["id"] for r in james["waitingForMe"]} & set(reviews),
        james["waitingForMe"],
    )
    check(
        "3 runs in flight are listed newest first",
        [r["id"] for r in o["runsInFlight"]][:2] == runs[::-1],
        o["runsInFlight"],
    )
    due = [r["id"] for r in o["casesDue"]]
    check(
        "4 the late and the shortly-due case are due, soonest first",
        due == [late, today] and o["counts"]["casesDue"] == 2,
        o["casesDue"],
    )
    check("4 a later, resolved or paused case is not due", not {later, done, paused} & set(due), due)
finish()
