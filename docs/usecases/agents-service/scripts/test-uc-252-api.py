"""uc-252 a builder archives a workflow and restores it, api layer: docs/usecases/agents-service/archive-a-workflow.md.

A real worker runs the workflow once; archiving it refuses every new start, live or test, and takes it off both
workflow lists while its run is kept; restoring it brings back the live version as it was. No model call is made."""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any

from usecase_harness import TEAM, agents, check, data, engine_worker, finish, until

DEFINITION = """
schemaVersion: 2
id: uc252_old_intake
name: Old intake (uc-252)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}
  - {id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {outcome: done}}
connections:
  - {from: {node: start, port: payload}, to: {node: done, port: in}}
"""
WF = "uc252_old_intake"


def start(api: Any, key: str, mode: str = "live") -> Any:
    return api.post("/v1/runs", json={"workflowId": WF, "mode": mode, "input": {}, "runKey": key}, headers=TEAM)


def ids(page: dict[str, Any], key: str) -> list[str]:
    return [str(w[key]) for w in page.get("data") or []]


with ExitStack() as stack:
    api = stack.enter_context(agents())
    created = api.post("/v1/workflows/definitions", json={"yaml": DEFINITION}, headers=TEAM)
    live = api.post(f"/v1/workflows/definitions/{WF}/publish-requests", json={}, headers=TEAM)
    check(
        "0 the workflow saves and goes live",
        created.status_code == 201 and data(live)["status"] == "approved",
        created.text[:300],
    )
    stack.enter_context(engine_worker("uc252"))
    run_id = str(data(start(api, "uc252-a"))["runId"])
    ran = until(
        lambda: (r := data(api.get(f"/v1/runs/{run_id}", headers=TEAM)) or {}).get("status") == "succeeded" and r
    )
    check("1 it runs once", bool(ran), run_id)

    archived = data(api.post(f"/v1/workflows/definitions/{WF}/archive", headers=TEAM))
    refused = [start(api, f"uc252-{m}", m) for m in ("live", "test")]
    codes = [(r.status_code, r.json().get("error", {}).get("code")) for r in refused]
    check(
        "2 archived, it starts no run, live or test",
        bool(archived.get("archivedAt")) and codes == [(409, "workflow_archived")] * 2,
        {"archivedAt": archived.get("archivedAt"), "codes": codes},
    )
    defs = data(api.get("/v1/workflows/definitions", headers=TEAM))
    merged = data(api.get("/v1/workflows?pageSize=200", headers=TEAM))
    shown = data(api.get("/v1/workflows/definitions?status=archived", headers=TEAM))
    kept = data(api.get(f"/v1/runs/{run_id}", headers=TEAM)) or {}
    check(
        "3 it leaves both lists unless archived ones are asked for, and its run is kept",
        WF not in ids(defs, "workflowId")
        and WF not in ids(merged, "id")
        and WF in ids(shown, "workflowId")
        and kept.get("id") == run_id,
        {"definitions": ids(defs, "workflowId"), "archived": ids(shown, "workflowId"), "run": kept.get("status")},
    )

    restored = data(api.post(f"/v1/workflows/definitions/{WF}/restore", headers=TEAM))
    again = start(api, "uc252-b")
    check(
        "4 restored, it serves its live version again and starts runs",
        restored.get("archivedAt") is None and restored.get("liveVersion") == 1 and again.status_code == 202,
        {"restored": {k: restored.get(k) for k in ("archivedAt", "liveVersion")}, "start": again.status_code},
    )

finish()
