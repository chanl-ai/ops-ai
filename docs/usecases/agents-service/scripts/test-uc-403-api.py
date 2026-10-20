"""uc-403 a workflow waits for a time or date and reminds a person, api layer:
docs/usecases/agents-service/wait-and-reminders.md.

A real worker runs three workflows (configuration below, nothing in code knows them): one waits two seconds, one waits
until a date read from its input, and one leaves a Human review waiting with a reminder about every two seconds. The
reminders are listed in Activity while the review waits and stop once it is decided. No model call is made."""

from __future__ import annotations

import time
from contextlib import ExitStack
from typing import Any

import httpx
from usecase_harness import AGENTS_PORT, TOOLS_PORT, agents, check, data, engine_worker, finish, tools, until

OPS = {"X-Team-Id": "team_ops"}
MAYA = {**OPS, "X-Dev-User": "m.okafor@northfieldbank.com"}

PAUSE = """
schemaVersion: 2
id: uc403_pause
name: Pause two seconds (uc-403)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Start}
  - {id: pause, type: ops.flow.wait, typeVersion: 1, name: Pause, parameters: {seconds: 2}}
  - {id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {outcome: done}}
connections:
  - {from: {node: start, port: payload}, to: {node: pause, port: in}}
  - {from: {node: pause, port: out}, to: {node: done, port: in}}
"""
DUE = """
schemaVersion: 2
id: uc403_due
name: Wait for the response date (uc-403)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Levy}
  - id: due
    type: ops.flow.wait
    typeVersion: 1
    name: Until the response date
    parameters: {mode: until, until: "$.input.respondBy"}
  - {id: done, type: ops.flow.end, typeVersion: 1, name: Due, parameters: {outcome: due}}
  - {id: bad, type: ops.flow.end, typeVersion: 1, name: Not a date, parameters: {outcome: not_a_date}}
connections:
  - {from: {node: start, port: payload}, to: {node: due, port: in}}
  - {from: {node: due, port: out}, to: {node: done, port: in}}
  - {from: {node: due, port: error}, to: {node: bad, port: in}}
"""
REMIND = """
schemaVersion: 2
id: uc403_remind
name: Check the levy, reminded (uc-403)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Levy}
  - id: check
    type: ops.flow.humanReview
    typeVersion: 1
    name: Check the levy
    parameters: {title: Check the levy, remindEveryHours: 0.0006}
  - {id: approved, type: ops.flow.end, typeVersion: 1, name: Approved, parameters: {outcome: approved}}
  - {id: rejected, type: ops.flow.end, typeVersion: 1, name: Rejected, parameters: {outcome: rejected}}
connections:
  - {from: {node: start, port: payload}, to: {node: check, port: in}}
  - {from: {node: check, port: approve}, to: {node: approved, port: in}}
  - {from: {node: check, port: reject}, to: {node: rejected, port: in}}
"""


def publish(api: httpx.Client, yaml: str, wid: str) -> tuple[bool, str]:
    saved = api.post("/v1/workflows/definitions", json={"yaml": yaml}, headers=OPS)
    live = api.post(f"/v1/workflows/definitions/{wid}/publish-requests", json={}, headers=OPS)
    ok = saved.status_code == 201 and (data(live) or {}).get("status") == "approved"
    return (
        ok,
        f"{wid}: {saved.status_code} {saved.text[:300]} | {live.status_code} status={(data(live) or {}).get('status')}",
    )


def run_of(api: httpx.Client, run_id: str) -> dict[str, Any]:
    return data(api.get(f"/v1/runs/{run_id}", headers=OPS)) or {}


def started(api: httpx.Client, workflow: str, payload: dict[str, Any]) -> str:
    return str(
        (data(api.post("/v1/runs", json={"workflowId": workflow, "input": payload}, headers=OPS)) or {})["runId"]
    )


def ended(api: httpx.Client, run_id: str, timeout: float = 30) -> dict[str, Any]:
    return until(lambda: (r := run_of(api, run_id)).get("status") in ("succeeded", "failed") and r, timeout) or {}


def reminders(api: httpx.Client, run_id: str) -> list[dict[str, Any]]:
    rows = data(api.get("/v1/activity", params={"kind": "reminder", "pageSize": 100}, headers=OPS)) or {}
    return [r for r in rows.get("data") or rows.get("rows") or [] if (r.get("ref") or {}).get("id") == run_id]


with ExitStack() as stack:
    stack.enter_context(tools({"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}))
    api = stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}"))
    published = [publish(api, y, w) for y, w in ((PAUSE, "uc403_pause"), (DUE, "uc403_due"), (REMIND, "uc403_remind"))]
    check("0 the three workflows save and go live", all(ok for ok, _ in published), [why for _, why in published])
    stack.enter_context(engine_worker("uc403", {"OPS_GATEWAY_URL": f"http://127.0.0.1:{TOOLS_PORT}"}))

    began = time.monotonic()
    pause = started(api, "uc403_pause", {})
    waiting = until(lambda: run_of(api, pause).get("status") == "waiting", 10)
    run = ended(api, pause)
    took = time.monotonic() - began
    check(
        "1 a two-second Wait reads waiting, then goes on by out once the time has passed",
        bool(waiting) and run.get("outcome") == "done" and took >= 2,
        {"waiting": waiting, "outcome": run.get("outcome"), "seconds": round(took, 1)},
    )

    past = ended(api, started(api, "uc403_due", {"respondBy": "2020-01-31"}), 10)
    junk_id = started(api, "uc403_due", {"respondBy": "next Friday"})
    junk = ended(api, junk_id, 10)
    step = next((s for s in junk.get("steps") or [] if s.get("nodeId") == "due"), {})
    check(
        "2 a past date goes on at once; a value that is not a date leaves by error, naming it",
        past.get("outcome") == "due"
        and junk.get("outcome") == "not_a_date"
        and (step.get("output") or {}).get("value") == "next Friday",
        {"past": past.get("outcome"), "junk": junk.get("outcome"), "step": step.get("output")},
    )

    remind = started(api, "uc403_remind", {})
    two = until(lambda: len(rows := reminders(api, remind)) >= 2 and rows, 30) or []
    still = run_of(api, remind).get("status")
    check(
        "3 a review left waiting is reminded and listed in Activity, and keeps waiting",
        len(two) >= 2 and still == "waiting" and all(r["status"] == "waiting" for r in two),
        {"reminders": [(r.get("title"), r.get("status")) for r in two], "run": still},
    )
    decided = api.post(f"/reviews/{remind}/decision", json={"decision": "approved"}, headers=MAYA)
    after = ended(api, remind, 10)
    count = len(reminders(api, remind))
    time.sleep(4)
    later = reminders(api, remind)
    check(
        "4 once the review is decided no reminder follows",
        decided.status_code == 200 and after.get("outcome") == "approved" and len(later) == count,
        {"decision": decided.status_code, "outcome": after.get("outcome"), "before": count, "after": len(later)},
    )

finish()
