"""uc-400 a workflow's branches join, api layer: docs/usecases/agents-service/branches-join.md.

A real worker runs a workflow that forks into two branches of different lengths and joins them (configuration
below, nothing in code knows it): the step after the Join runs once with both branches' outputs by the step they came
from. A second run skips the longer branch at an If, which goes straight to the Join, and the Join still runs once,
naming the skipped branch's last step null. Saving the same fork with a plain step where the branches meet is warned,
not refused. No model call is made."""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any

import httpx
from usecase_harness import AGENTS_PORT, TEAM, TOOLS_PORT, agents, check, data, engine_worker, finish, tools, until

SET = "type: ops.data.set, typeVersion: 1"
JOIN = "type: ops.flow.join, typeVersion: 1, name: Join"
PLAIN = f"{SET}, name: Meet, parameters: {{values: {{met: true}}}}"


def definition(wid: str, meet: str) -> str:
    return f"""
schemaVersion: 2
id: {wid}
name: Two checks then one decision (uc-400)
nodes:
  - {{id: start, type: ops.trigger.request, typeVersion: 1, name: Request}}
  - {{id: fields, {SET}, name: Fields, parameters: {{values: {{amount: "$.input.amount"}}}}}}
  - {{id: limits, {SET}, name: Check limits, parameters: {{values: {{withinLimit: true}}}}}}
  - id: sanctions
    type: ops.flow.if
    typeVersion: 1
    name: Screen the payee?
    parameters: {{conditions: [{{left: "$.input.screen", op: eq, right: true}}]}}
  - {{id: screen, {SET}, name: Screen, parameters: {{values: {{listed: false}}}}}}
  - {{id: screened, {SET}, name: Screened, parameters: {{values: {{clear: true}}}}}}
  - {{id: meet, {meet}}}
  - {{id: decide, {SET}, name: Decide, parameters: {{values: {{both: "$.nodes.meet.out"}}}}}}
  - {{id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {{outcome: decided}}}}
connections:
  - {{from: {{node: start, port: payload}}, to: {{node: fields, port: in}}}}
  - {{from: {{node: fields, port: out}}, to: {{node: limits, port: in}}}}
  - {{from: {{node: fields, port: out}}, to: {{node: sanctions, port: in}}}}
  - {{from: {{node: sanctions, port: "true"}}, to: {{node: screen, port: in}}}}
  - {{from: {{node: sanctions, port: "false"}}, to: {{node: meet, port: in}}}}
  - {{from: {{node: screen, port: out}}, to: {{node: screened, port: in}}}}
  - {{from: {{node: screened, port: out}}, to: {{node: meet, port: in}}}}
  - {{from: {{node: limits, port: out}}, to: {{node: meet, port: in}}}}
  - {{from: {{node: meet, port: out}}, to: {{node: decide, port: in}}}}
  - {{from: {{node: decide, port: out}}, to: {{node: done, port: in}}}}
"""


def start(api: httpx.Client, run_input: dict[str, Any]) -> dict[str, Any]:
    started = api.post("/v1/runs", json={"workflowId": "uc400_branches", "input": run_input}, headers=TEAM)
    run_id = str((data(started) or {}).get("runId"))

    def ended() -> dict[str, Any] | None:
        run = data(api.get(f"/v1/runs/{run_id}", headers=TEAM)) or {}
        return run if run.get("status") in ("succeeded", "failed") else None

    return until(ended) or {}


def steps_of(run: dict[str, Any], node: str) -> list[dict[str, Any]]:
    return [s for s in run.get("steps") or [] if s.get("nodeId") == node]


def both(run: dict[str, Any]) -> Any:
    [decide] = steps_of(run, "decide") or [{}]
    return (decide.get("output") or {}).get("both")


with ExitStack() as stack:
    stack.enter_context(tools({"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}))
    api = stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}"))
    created = api.post("/v1/workflows/definitions", json={"yaml": definition("uc400_branches", JOIN)}, headers=TEAM)
    live = api.post("/v1/workflows/definitions/uc400_branches/publish-requests", json={}, headers=TEAM)
    check(
        "0 the workflow with a Join saves with no warning and goes live",
        created.status_code == 201
        and (data(created) or {}).get("warnings") == []
        and (data(live) or {}).get("status") == "approved",
        created.text[:400],
    )
    stack.enter_context(engine_worker("uc400", {"OPS_GATEWAY_URL": f"http://127.0.0.1:{TOOLS_PORT}"}))

    run = start(api, {"amount": 900, "screen": True})
    joined = both(run) or {}
    check(
        "1 both branches reach the Join; the step after it runs once with each branch by the step it came from",
        run.get("status") == "succeeded"
        and len(steps_of(run, "decide")) == 1
        and joined.get("limits") == {"withinLimit": True}
        and joined.get("screened") == {"clear": True},
        {"status": run.get("status"), "both": joined},
    )

    run2 = start(api, {"amount": 50, "screen": False})
    joined2 = both(run2) or {}
    check(
        "2 the If skips the longer branch: its last step is null, and the Join and the step after it run once",
        run2.get("status") == "succeeded"
        and len(steps_of(run2, "meet")) == 1
        and len(steps_of(run2, "decide")) == 1
        and joined2.get("limits") == {"withinLimit": True}
        and "screened" in joined2
        and joined2["screened"] is None,
        {"status": run2.get("status"), "both": joined2, "meet": steps_of(run2, "meet")},
    )

    plain = api.post("/v1/workflows/definitions", json={"yaml": definition("uc400_no_join", PLAIN)}, headers=TEAM)
    warned = [w for w in (data(plain) or {}).get("warnings") or [] if w.get("node") == "meet"]
    check(
        "3 the same fork meeting at a plain step saves, with a warning that it runs once per branch",
        plain.status_code == 201 and len(warned) == 1 and "once per branch" in warned[0]["message"],
        plain.text[:400],
    )

finish()
