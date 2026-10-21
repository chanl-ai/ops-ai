# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-209 a workflow starts a child workflow for each item of a list, api layer:
docs/usecases/agents-service/start-a-workflow-per-item.md.

Runs against the shared stack (`OPS_STACK_AUTH=platform make up`): the worker runs the intake and its children."""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import httpx
from usecase_harness import check, finish

PLATFORM = f"http://127.0.0.1:{os.environ.get('OPS_PLATFORM_PORT', '8710')}"
AGENTS = f"http://127.0.0.1:{os.environ.get('OPS_AGENTS_PORT', '8700')}"
RUN = uuid.uuid4().hex[:8]
CHILD, INTAKE = f"uc209_case_{RUN}", f"uc209_intake_{RUN}"
PERSONS = [{"name": "Ana Silva"}, {"name": "Bo Chen"}, {"name": "Cy Okafor"}]


def headers(email: str, team: str) -> dict[str, str]:
    r = httpx.post(f"{PLATFORM}/v1/auth/sign-in", json={"email": email, "password": "northfield-demo"}, timeout=30)
    assert r.status_code == 200, f"sign-in as {email}: {r.status_code} {r.text[:200]}"
    return {"Authorization": f"Bearer {r.json()['data']['token']}", "X-Team-Id": team}


def node(id_: str, type_: str, name: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"id": id_, "type": type_, "typeVersion": 1, "name": name, "parameters": parameters or {}}


def wire(a: str, port: str, b: str) -> dict[str, Any]:
    return {"from": {"node": a, "port": port}, "to": {"node": b, "port": "in"}}


def intake(start: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "id": INTAKE,
        "name": f"Levy intake {RUN}",
        "nodes": [
            node("in", "ops.trigger.request", "Request"),
            node("open", "ops.action.workflow", "Open a case per person", start),
            node("done", "ops.flow.end", "Cases opened", {"outcome": "cases_opened"}),
            node("failed", "ops.flow.end", "Not opened", {"outcome": "not_opened"}),
        ],
        "connections": [
            wire("in", "payload", "open"),
            wire("open", "started", "done"),
            wire("open", "error", "failed"),
        ],
    }


CASE = {
    "schemaVersion": 2,
    "id": CHILD,
    "name": f"Levy case {RUN}",
    "nodes": [node("in", "ops.trigger.request", "Request"), node("done", "ops.flow.end", "Open", {"outcome": "open"})],
    "connections": [wire("in", "payload", "done")],
}
PER_PERSON = {
    "workflow": CHILD,
    "forEach": "$.input.persons",
    "input": {"name": "$.item.name", "position": "$.index", "notice": "$.input.notice"},
}

james = headers("j.richardson@harborpine.example", "team_ops")
api = httpx.Client(base_url=AGENTS, timeout=60, headers=james)


def runs(workflow: str) -> list[dict[str, Any]]:
    return list(api.get("/v1/runs", params={"workflowId": workflow, "pageSize": 100}).json()["data"]["data"])


def settled(run_id: str) -> dict[str, Any]:
    end = time.monotonic() + 60
    while time.monotonic() < end:
        r = api.get(f"/v1/runs/{run_id}").json()["data"]
        if r["status"] in ("succeeded", "failed", "cancelled"):
            return r
        time.sleep(1)
    return api.get(f"/v1/runs/{run_id}").json()["data"]


published = []
for d in (CASE, intake(PER_PERSON)):
    saved = api.post("/v1/workflows/definitions", json={"definition": d})
    live = api.post(f"/v1/workflows/definitions/{d['id']}/publish-requests", json={})
    published.append((saved.status_code, live.status_code, live.json().get("data", {}).get("status")))
check("1 James publishes the case and the intake", published == [(201, 201, "approved")] * 2, published)

try:
    started = api.post("/v1/runs", json={"workflowId": INTAKE, "input": {"notice": f"N-{RUN}", "persons": PERSONS}})
    parent = settled(started.json()["data"]["runId"])
    end = time.monotonic() + 30
    while time.monotonic() < end and sum(r["status"] == "succeeded" for r in runs(CHILD)) < 3:
        time.sleep(1)
    children = sorted(runs(CHILD), key=lambda r: r["input"]["position"])
    check(
        "2 the intake succeeds and three live children start in its team, created by its run",
        parent["status"] == "succeeded"
        and [c["input"] for c in children]
        == [{"name": p["name"], "position": i, "notice": f"N-{RUN}"} for i, p in enumerate(PERSONS)]
        and {(c["mode"], c["createdBy"], c["status"]) for c in children}
        == {("live", f"run:{parent['id']}", "succeeded")},
        (parent["status"], parent.get("error"), [(c["mode"], c["createdBy"], c["status"]) for c in children]),
    )
    step = next((s for s in parent["steps"] if s.get("nodeId") == "open"), {})
    listed = [r["runId"] for r in ((step.get("output") or {}).get("runs") or [])]
    check(
        "3 the run page's Start workflow step lists the children in order", listed == [c["id"] for c in children], step
    )

    tested = api.post(
        "/v1/runs", json={"workflowId": INTAKE, "mode": "test", "input": {"notice": "T", "persons": PERSONS[:1]}}
    )
    trial = settled(tested.json()["data"]["runId"])
    test_children = [r for r in runs(CHILD) if r["createdBy"] == f"run:{trial['id']}"]
    check(
        "4 a test run's children are test runs",
        trial["status"] == "succeeded" and [c["mode"] for c in test_children] == ["test"],
        (trial["status"], trial.get("error"), test_children),
    )

    stray = intake({"workflow": CHILD, "input": {"name": "$.item.name"}}) | {"id": f"{INTAKE}_stray"}
    refused = api.post("/v1/workflows/definitions", json={"definition": stray})
    check(
        "5 a step reading $.item with no For each is refused by its checks",
        refused.status_code >= 400 and "item_outside_loop" in refused.text,
        refused.text[:300],
    )
finally:
    for wid in (INTAKE, CHILD):
        api.post(f"/v1/workflows/definitions/{wid}/pause")
finish()
