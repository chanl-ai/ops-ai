"""uc-workflows-1 a schedule trigger starts one run when due, api layer:
docs/usecases/agents-service/a-schedule-starts-a-run-once.md.

A builder saves and publishes a workflow whose trigger is Schedule. A real worker runs it. A tick that is due starts
one run with the tick's values; the same tick key again starts no second run; another key starts another; a tick set
for an hour from now stays queued while the due ones finish; a tick missing a required value is refused. No model call
is made."""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any

import httpx
from usecase_harness import AGENTS_PORT, TEAM, TOOLS_PORT, agents, check, data, engine_worker, finish, tools, until

WID = "ucwf1_morning_report"
YAML = f"""
schemaVersion: 2
id: {WID}
name: Morning report (uc-workflows-1)
nodes:
  - id: start
    type: ops.trigger.schedule
    typeVersion: 1
    name: Due
    parameters:
      key: morning
      inputSchema:
        type: object
        additionalProperties: false
        required: [day]
        properties: {{day: {{type: string}}}}
  - id: done
    type: ops.flow.end
    typeVersion: 1
    name: Ticked
    parameters: {{outcome: ticked, output: {{day: "$.input.day"}}}}
connections:
  - {{from: {{node: start, port: payload}}, to: {{node: done, port: in}}}}
"""


def tick(api: httpx.Client, key: str, day: str | None, after_seconds: float = 0) -> httpx.Response:
    body: dict[str, Any] = {"workflowId": WID, "input": {} if day is None else {"day": day}, "runKey": key}
    if after_seconds:
        body["afterSeconds"] = after_seconds
    return api.post("/v1/runs", json=body, headers=TEAM)


def day_of(run: dict[str, Any]) -> Any:
    steps = [s for s in run.get("steps") or [] if s.get("nodeId") == "done"]
    return (((steps[-1].get("output") or {}).get("output") or {}).get("day")) if steps else None


def ended(api: httpx.Client, run_id: str) -> dict[str, Any]:
    def done() -> dict[str, Any] | None:
        run = data(api.get(f"/v1/runs/{run_id}", headers=TEAM)) or {}
        return run if run.get("status") in ("succeeded", "failed") else None

    return until(done, timeout=60) or {}


with ExitStack() as stack:
    stack.enter_context(tools({"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}))
    api = stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}"))
    saved = api.post("/v1/workflows/definitions", json={"yaml": YAML}, headers=TEAM)
    live = api.post(f"/v1/workflows/definitions/{WID}/publish-requests", json={}, headers=TEAM)
    check(
        "0 the scheduled workflow saves and goes live",
        saved.status_code == 201 and (data(live) or {}).get("status") == "approved",
        f"{saved.status_code} {live.status_code} {live.text[-200:]}",
    )
    stack.enter_context(engine_worker("ucwf1", {"OPS_GATEWAY_URL": f"http://127.0.0.1:{TOOLS_PORT}"}))

    first = tick(api, "morning-2026-11-10", "monday")
    first_body = data(first) or {}
    run = ended(api, str(first_body.get("runId")))
    steps = [s for s in run.get("steps") or [] if s.get("nodeId") == "done"]
    check(
        "1 a due tick starts one run that ends with the tick's day",
        first.status_code == 202
        and first_body.get("created") is True
        and run.get("status") == "succeeded"
        and bool(steps)
        and ((steps[-1].get("output") or {}).get("output") or {}) == {"day": "monday"},
        {"http": first.status_code, "started": first_body, "status": run.get("status"), "steps": steps},
    )

    again = tick(api, "morning-2026-11-10", "monday")
    again_body = data(again) or {}
    check(
        "2 the same tick key again starts no second run and returns the first",
        again.status_code == 200
        and again_body.get("created") is False
        and again_body.get("runId") == first_body.get("runId"),
        {"http": again.status_code, "body": again_body},
    )

    next_day = tick(api, "morning-2026-11-11", "tuesday")
    next_body = data(next_day) or {}
    next_run = ended(api, str(next_body.get("runId")))
    check(
        "3 a tick with another key starts another run with its own day",
        next_day.status_code == 202
        and next_body.get("runId") != first_body.get("runId")
        and next_run.get("status") == "succeeded"
        and day_of(next_run) == "tuesday",
        {"http": next_day.status_code, "day": day_of(next_run), "status": next_run.get("status")},
    )

    later = tick(api, "morning-2026-11-12", "wednesday", after_seconds=3600)
    later_body = data(later) or {}
    # The worker has finished the due ticks by now, so a run still queued was held by its due time, not left behind.
    held = data(api.get(f"/v1/runs/{later_body.get('runId')}", headers=TEAM)) or {}
    check(
        "4 a tick due in an hour stays queued while the due ones have finished",
        later.status_code == 202 and held.get("status") == "queued" and not held.get("steps"),
        {"http": later.status_code, "status": held.get("status"), "steps": held.get("steps")},
    )

    by_hand = api.post("/v1/runs/start", json={"workflowId": WID, "values": {}}, headers=TEAM)
    check(
        "5 Fire now without the required day is refused naming the day",
        by_hand.status_code == 422 and "day" in by_hand.text,
        f"{by_hand.status_code} {by_hand.text[:300]}",
    )
    bad = tick(api, "morning-2026-11-13", None)
    check(
        "6 a tick without the required day is refused and starts no run",
        bad.status_code == 422 and "day" in bad.text,
        f"{bad.status_code} {bad.text[:300]}",
    )

    listed = data(api.get("/v1/runs", params={"workflowId": WID, "pageSize": 100}, headers=TEAM)) or {}
    status_of = {r["id"]: r["status"] for r in listed.get("data") or []}
    check(
        "7 the runs from steps 1, 3 and 4 are listed as succeeded, succeeded and queued",
        [status_of.get(r) for r in (first_body.get("runId"), next_body.get("runId"), later_body.get("runId"))]
        == ["succeeded", "succeeded", "queued"],
        status_of,
    )

finish()
