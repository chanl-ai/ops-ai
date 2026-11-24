"""uc-workflows-1 a schedule trigger starts one run when due, api layer:
docs/usecases/agents-service/a-schedule-starts-a-run-once.md.

A builder saves and publishes a workflow whose trigger is Schedule. A real worker runs it. A tick that is due starts
one run with the tick's values; the same tick key again starts no second run; another key starts another; a tick set
for an hour from now stays queued while the due ones finish; a tick missing a required value is refused. Then the
clock: a second workflow with a saved schedule, every minute, gets one run from the worker's own schedule clock at its
next slot, keyed by the slot and started by the schedule, and one run per slot only. No model call is made."""

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


CLOCKED = "ucwf1_every_minute"
CLOCKED_YAML = f"""
schemaVersion: 2
id: {CLOCKED}
name: Every minute (uc-workflows-1)
nodes:
  - id: start
    type: ops.trigger.schedule
    typeVersion: 1
    name: Due
    parameters: {{}}
  - id: done
    type: ops.flow.end
    typeVersion: 1
    name: Ticked
    parameters: {{outcome: ticked, output: {{dueAt: "$.input.dueAt"}}}}
connections:
  - {{from: {{node: start, port: payload}}, to: {{node: done, port: in}}}}
"""
# Every minute is under the install's default floor of 5; this run's install lowers it so the clock is seen in a minute.
FLOOR = {"OPS_SCHEDULE_FLOOR_MINUTES": "1"}


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
    api = stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}", env=FLOOR))
    saved = api.post("/v1/workflows/definitions", json={"yaml": YAML}, headers=TEAM)
    live = api.post(f"/v1/workflows/definitions/{WID}/publish-requests", json={}, headers=TEAM)
    check(
        "0 the scheduled workflow saves and goes live",
        saved.status_code == 201 and (data(live) or {}).get("status") == "approved",
        f"{saved.status_code} {live.status_code} {live.text[-200:]}",
    )
    clocked = api.post("/v1/workflows/definitions", json={"yaml": CLOCKED_YAML}, headers=TEAM)
    clocked_live = api.post(f"/v1/workflows/definitions/{CLOCKED}/publish-requests", json={}, headers=TEAM)
    every_minute = {"kind": "every", "every": 1, "unit": "minutes", "tz": "UTC"}
    schedule_url = f"/v1/workflows/definitions/{CLOCKED}/triggers/start/schedule"
    saved_schedule = api.put(schedule_url, json={"rule": every_minute}, headers=TEAM)
    check(
        "8 a schedule saved on a live workflow applies at once, in words, with its next runs",
        clocked.status_code == 201
        and (data(clocked_live) or {}).get("status") == "approved"
        and saved_schedule.status_code == 200
        and (data(saved_schedule) or {}).get("words", "").startswith("Every minute")
        and len((data(saved_schedule) or {}).get("nextRuns") or []) == 3,
        f"{clocked.status_code} {clocked_live.status_code} {saved_schedule.status_code} {saved_schedule.text[:300]}",
    )
    stack.enter_context(
        engine_worker("ucwf1", {"OPS_GATEWAY_URL": f"http://127.0.0.1:{TOOLS_PORT}", **FLOOR})
    )

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

    def clock_runs() -> list[dict[str, Any]]:
        got = data(api.get("/v1/runs", params={"workflowId": CLOCKED, "pageSize": 100}, headers=TEAM)) or {}
        return list(got.get("data") or [])

    # The clock's first pass sees the schedule and starts nothing; the pass a minute later starts the slot's run.
    first_clocked = until(clock_runs, timeout=150) or []
    started = ended(api, str(first_clocked[0]["id"])) if first_clocked else {}
    check(
        "9 the worker's schedule clock starts one run at the next slot, started by the schedule, with the slot",
        len(first_clocked) == 1
        and started.get("status") == "succeeded"
        and started.get("createdBy") == f"trigger:schedule:{CLOCKED}"
        and str((started.get("input") or {}).get("dueAt", "")).endswith(":00Z"),
        {k: started.get(k) for k in ("status", "createdBy", "input")} or first_clocked,
    )
    shown = data(api.get(schedule_url, headers=TEAM)) or {}
    check(
        "10 the schedule shows the slot it ran as its last, with that run's due time",
        shown.get("lastOutcome") in ("ran", "late")
        and shown.get("lastSlotAt") is not None
        and shown.get("lastSlotAt") >= str((started.get("input") or {}).get("dueAt")),
        {"last": (shown.get("lastSlotAt"), shown.get("lastOutcome")), "dueAt": (started.get("input") or {}).get("dueAt")},
    )

    # A daily rule in a zone whose clocks change: the preview counts from a chosen instant, so the days around both
    # changes are read here. Each local day has exactly one slot, at the local time (the first minute after a gap, the
    # first of a repeated hour).
    def preview_from(rule: dict[str, Any], after: str) -> list[str]:
        got = data(api.post("/v1/schedules/preview", json={"rule": rule, "after": after}, headers=TEAM)) or {}
        return list(got.get("nextRuns") or [])

    night = {"kind": "daily", "time": "01:30", "tz": "Europe/London"}
    spring = preview_from(night, "2026-03-27T12:00:00Z")
    autumn = preview_from(night, "2026-10-23T12:00:00Z")
    check(
        "13 a daily rule runs once on each day the clocks change, at its local time, never twice and never skipped",
        spring == ["2026-03-28T01:30:00Z", "2026-03-29T01:00:00Z", "2026-03-30T00:30:00Z"]
        and autumn == ["2026-10-24T00:30:00Z", "2026-10-25T00:30:00Z", "2026-10-26T01:30:00Z"],
        {"spring": spring, "autumn": autumn},
    )
    unknown = api.post(
        "/v1/schedules/preview", json={"rule": {"kind": "daily", "at": "07:30", "tz": "UTC"}}, headers=TEAM
    )
    check(
        "14 a rule with a field the kind does not have is refused naming the field",
        unknown.status_code == 422 and (unknown.json().get("error") or {}).get("details", {}).get("field") == "at",
        f"{unknown.status_code} {unknown.text[:300]}",
    )

finish()
