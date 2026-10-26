"""uc-526 another team's records answer not found, api layer:
docs/usecases/agents-service/another-team-s-records-answer-not.md. platform-service signs the seeded people in and
agents-service verifies their tokens, as the console runs them. Priya makes a task type, a case type, a case, a
workflow and a run in Operations; Sam, acting in Security, reads each and gets the not-found answer with no team named,
while Priya reads each. No model call is made."""

from __future__ import annotations

from typing import Any

import httpx
from usecase_harness import bearer, check, data, finish, people_stack, signed_in

DEFINITION = """
schemaVersion: 2
id: uc526_note
name: Note (uc-526)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}
  - {id: done, type: ops.flow.end, typeVersion: 1, name: End}
connections:
  - {from: {node: start, port: payload}, to: {node: done, port: in}}
"""


def made(r: httpx.Response, what: str) -> dict[str, Any]:
    ok = r.status_code in (200, 201, 202)
    check(f"Priya makes {what} in Operations", ok, r.text[:200])
    return data(r) if ok else {}


def walk(agents: httpx.Client, ops: dict[str, str], security: dict[str, str], what: str, path: str) -> None:
    mine = agents.get(path, headers=ops)
    check(f"Priya reads {what} in Operations", mine.status_code == 200, mine.text[:200])
    theirs = agents.get(path, headers=security)
    check(f"Sam in Security gets not found for {what}", theirs.status_code == 404, theirs.text[:200])
    check(f"the answer for {what} names no team", "team_ops" not in theirs.text and "Operations" not in theirs.text)


with people_stack() as (api, agents):
    ops = bearer(signed_in(api, "p.shah@harborpine.example"), "team_ops")
    security = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")

    task_type = made(
        agents.post(
            "/v1/task-types",
            json={"id": "uc526_task", "copyOf": {"id": "write_approval"}, "name": "Vendor change (uc-526)"},
            headers=ops,
        ),
        "a task type",
    )
    case_type = made(
        agents.post(
            "/v1/case-types",
            json={"id": "uc526_case", "copyOf": {"id": "complaint"}, "name": "Complaint copy (uc-526)"},
            headers=ops,
        ),
        "a case type",
    )
    case = made(
        agents.post(
            "/v1/cases",
            json={"subject": "Card dispute (uc-526)", "priority": "high", "customerId": "C-526", "customerName": "Ann"},
            headers=ops,
        ),
        "a case",
    )
    made(agents.post("/v1/workflows/definitions", json={"yaml": DEFINITION}, headers=ops), "a workflow")
    live = agents.post("/v1/workflows/definitions/uc526_note/publish-requests", json={}, headers=ops)
    check("the workflow goes live", live.status_code in (200, 201) and data(live)["status"] == "approved", live.text)
    run = made(agents.post("/v1/runs", json={"workflowId": "uc526_note", "input": {}}, headers=ops), "a run")

    walk(agents, ops, security, "the task type", "/v1/task-types/uc526_task")
    walk(agents, ops, security, "the case type", "/v1/case-types/uc526_case")
    walk(agents, ops, security, "the case", f"/v1/cases/{case.get('id', 'case_missing')}")
    walk(agents, ops, security, "the run", f"/v1/runs/{run.get('runId', 'wfrun_missing')}")
    walk(agents, ops, security, "the workflow", "/v1/workflows/definitions/uc526_note")
    del task_type, case_type

finish()
