"""uc-402 a workflow waits for its children, api layer: docs/usecases/agents-service/wait-for-children.md.

A real worker runs a parent that reads three attachments, each in a child run, two at a time (configuration below,
nothing in code knows it). One child cannot read its file and ends failed. The parent waits, then goes on once with
each child's outcome and output in item order, the failed one listed, and finishes. No model call is made."""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any

import httpx
from usecase_harness import AGENTS_PORT, TEAM, TOOLS_PORT, agents, check, data, engine_worker, finish, tools, until

CHILD = """
schemaVersion: 2
id: uc402_read_one
name: Read one attachment (uc-402)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Attachment}
  - id: readable
    type: ops.flow.if
    typeVersion: 1
    name: Readable?
    parameters: {conditions: [{left: "$.input.name", op: eq, right: "scan.pdf"}]}
  - id: unreadable
    type: ops.flow.end
    typeVersion: 1
    name: Unreadable
    parameters: {outcome: unreadable, result: failed}
  - id: read
    type: ops.flow.end
    typeVersion: 1
    name: Read
    parameters: {outcome: read, output: {file: "$.input.name"}}
connections:
  - {from: {node: start, port: payload}, to: {node: readable, port: in}}
  - {from: {node: readable, port: "true"}, to: {node: unreadable, port: in}}
  - {from: {node: readable, port: "false"}, to: {node: read, port: in}}
"""
PARENT = """
schemaVersion: 2
id: uc402_letter
name: Read every attachment (uc-402)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Letter}
  - id: each
    type: ops.action.workflow
    typeVersion: 1
    name: Read each attachment
    parameters:
      workflow: uc402_read_one
      forEach: "$.input.files"
      input: {name: "$.item.name"}
      wait: true
      batchSize: 2
  - {id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {outcome: read, output: "$.nodes.each.out"}}
  - {id: failed, type: ops.flow.end, typeVersion: 1, name: Failed, parameters: {outcome: failed, result: failed}}
connections:
  - {from: {node: start, port: payload}, to: {node: each, port: in}}
  - {from: {node: each, port: done}, to: {node: done, port: in}}
  - {from: {node: each, port: error}, to: {node: failed, port: in}}
"""
FILES = {"files": [{"name": "levy.pdf"}, {"name": "scan.pdf"}, {"name": "id.pdf"}]}


def publish(api: httpx.Client, yaml: str, wid: str) -> tuple[bool, str]:
    saved = api.post("/v1/workflows/definitions", json={"yaml": yaml}, headers=TEAM)
    live = api.post(f"/v1/workflows/definitions/{wid}/publish-requests", json={}, headers=TEAM)
    ok = saved.status_code == 201 and (data(live) or {}).get("status") == "approved"
    return ok, f"{saved.status_code} | {live.status_code} status={(data(live) or {}).get('status')} {live.text[-300:]}"


def ended(api: httpx.Client, run_id: str) -> dict[str, Any]:
    def done() -> dict[str, Any] | None:
        run = data(api.get(f"/v1/runs/{run_id}", headers=TEAM)) or {}
        return run if run.get("status") in ("succeeded", "failed") else None

    return until(done, timeout=90) or {}


with ExitStack() as stack:
    stack.enter_context(tools({"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}))
    api = stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}"))
    child_ok, child_why = publish(api, CHILD, "uc402_read_one")
    parent_ok, parent_why = publish(api, PARENT, "uc402_letter")
    check("0 the child and parent workflows save and go live", child_ok and parent_ok, [child_why, parent_why])
    stack.enter_context(engine_worker("uc402", {"OPS_GATEWAY_URL": f"http://127.0.0.1:{TOOLS_PORT}"}))

    started = api.post("/v1/runs", json={"workflowId": "uc402_letter", "input": FILES}, headers=TEAM)
    run = ended(api, str((data(started) or {}).get("runId")))
    steps = [s for s in run.get("steps") or [] if s.get("nodeId") == "each"]
    out = (steps[-1].get("output") if steps else None) or {}
    children = out.get("children") or []
    check(
        "1 the parent finishes after its children, the step going on once",
        run.get("status") == "succeeded" and len(steps) == 1 and steps[0].get("port") == "done",
        {"status": run.get("status"), "steps": steps},
    )
    check(
        "2 each child's outcome and output in item order, the unreadable one listed, not failing the parent",
        [(c["index"], c["outcome"]) for c in children] == [(0, "read"), (1, "unreadable"), (2, "read")]
        and children[0]["output"] == {"file": "levy.pdf"}
        and out.get("counts") == {"read": 2, "unreadable": 1},
        out,
    )

finish()
