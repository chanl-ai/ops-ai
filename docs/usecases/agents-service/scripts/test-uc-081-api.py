"""uc-081 basic nodes run through the queue, and a worker killed after the tool step leaves the tool called once, api
layer: docs/usecases/agents-service/workflow-runner-basic-nodes.md. agents-service runs on the scripted model with
tools-service as its gateway and the core bank fake behind it; workers are `python -m ops_agents.api.worker`
processes this script starts and kills. No model call is made.

Set OPS_ENGINE_FAULT_IGNORE_RECORDED=1 to run the non-vacuous variant: the second run's tool is then called twice and
the "called once" check fails."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from collections.abc import Callable, Generator
from contextlib import ExitStack, contextmanager
from typing import Any

import httpx
from usecase_harness import (
    AGENTS_DIR,
    AGENTS_PORT,
    DB,
    LOG_DIR,
    TEAM,
    TOOLS_PORT,
    _env,  # pyright: ignore[reportPrivateUsage]
    agents,
    check,
    core_bank,
    data,
    finish,
    publish_bank_module,
    sse,
    tools,
)

MAYA = {**TEAM, "X-Dev-User": "m.okafor@northfieldbank.com"}
DEFINITION = """
schemaVersion: 2
id: uc081_refund_check
name: Refund check (uc-081)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Request}
  - id: fields
    type: ops.data.set
    typeVersion: 1
    name: Set fields
    parameters: {values: {customer: "$.input.customerId", amount: "$.input.amount"}}
  - id: big
    type: ops.flow.if
    typeVersion: 1
    name: Over 100
    parameters: {conditions: [{left: "$.nodes.fields.out.amount", op: gt, right: 100}]}
  - id: lookup
    type: ops.action.tool
    typeVersion: 1
    name: Look up the customer
    parameters: {operation: get_customer, input: {customer_id: "$.nodes.fields.out.customer"}}
  - id: review
    type: ops.flow.humanReview
    typeVersion: 1
    name: Review the refund
    parameters: {title: Refund over 100, summary: "$.nodes.lookup.out.name"}
  - {id: approved, type: ops.flow.end, typeVersion: 1, name: Approved, parameters: {outcome: approved}}
  - {id: rejected, type: ops.flow.end, typeVersion: 1, name: Rejected, parameters: {outcome: rejected}}
  - {id: small, type: ops.flow.end, typeVersion: 1, name: Small, parameters: {outcome: small}}
  - {id: failed, type: ops.flow.end, typeVersion: 1, name: Failed, parameters: {outcome: tool_failed}}
connections:
  - {from: {node: start, port: payload}, to: {node: fields, port: in}}
  - {from: {node: fields, port: out}, to: {node: big, port: in}}
  - {from: {node: big, port: "true"}, to: {node: lookup, port: in}}
  - {from: {node: big, port: "false"}, to: {node: small, port: in}}
  - {from: {node: lookup, port: ok}, to: {node: review, port: in}}
  - {from: {node: lookup, port: refused}, to: {node: failed, port: in}}
  - {from: {node: lookup, port: error}, to: {node: failed, port: in}}
  - {from: {node: review, port: approve}, to: {node: approved, port: in}}
  - {from: {node: review, port: reject}, to: {node: rejected, port: in}}
"""
PAYLOAD = {"customerId": "CUS-1001", "amount": 250}
LEASE_TTL = "3"


@contextmanager
def worker(name: str, fault: dict[str, str] | None = None) -> Generator[subprocess.Popen[bytes]]:
    """One worker process on the run's database and gateway, with a short lease so a takeover takes seconds."""
    env = _env()
    pg = os.environ.get("OPS_PG_PORT", "5477")
    env |= {
        "OPS_DATABASE_URL": f"postgresql+asyncpg://ops:ops@localhost:{pg}/{DB}",
        "OPS_GATEWAY_URL": f"http://127.0.0.1:{TOOLS_PORT}",
        "OPS_LEASE_TTL_SECONDS": LEASE_TTL,
        "OPS_ENGINE_POLL_SECONDS": "0.2",
        **(fault or {}),
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / f"worker-{name}.log").open("ab") as fh:
        proc = subprocess.Popen(
            ["uv", "run", "python", "-m", "ops_agents.api.worker"], cwd=AGENTS_DIR, env=env, stdout=fh, stderr=fh
        )
    try:
        yield proc
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()


def until(what: Callable[[], Any], timeout: float = 60) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if found := what():
            return found
        time.sleep(0.3)
    return None


def run_of(api: httpx.Client, run_id: str) -> dict[str, Any]:
    return data(api.get(f"/v1/runs/{run_id}", headers=TEAM)) or {}


def status_is(api: httpx.Client, run_id: str, *wanted: str) -> Callable[[], dict[str, Any] | None]:
    def probe() -> dict[str, Any] | None:
        r = run_of(api, run_id)
        return r if r.get("status") in wanted else None

    return probe


def start_run(api: httpx.Client, key: str) -> str:
    res = api.post("/v1/runs", json={"workflowId": "uc081_refund_check", "input": PAYLOAD, "runKey": key}, headers=TEAM)
    check(f"run {key} is accepted (202)", res.status_code == 202, res.text[:300])
    return str(data(res)["runId"])


def tool_calls(gw: httpx.Client, run_id: str) -> list[dict[str, Any]]:
    rows = data(gw.get("/v1/executions", params={"thread": run_id, "pageSize": 200}))["data"]
    return [r for r in rows if r["target"] == "get_customer"]


def main() -> None:
    with ExitStack() as stack:
        bank = stack.enter_context(core_bank())
        agents_url = f"http://127.0.0.1:{AGENTS_PORT}"
        gw = stack.enter_context(tools({**bank["settings"], "OPS_AGENTS_URL": agents_url}))
        api = stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}"))
        gw.post("/v1/egress/hosts", json={"value": bank["host"], "note": "uc-081"})
        gw.post("/v1/egress/ranges", json={"value": bank["range"], "note": "uc-081"})
        gw.post("/v1/secrets", json={"name": "BANK_API_KEY", "value": "dev-bank-key"})
        publish_bank_module(gw, bank["host"])

        created = api.post("/v1/workflows/definitions", json={"yaml": DEFINITION}, headers=TEAM)
        check("the YAML definition is stored (201) with every check passing", created.status_code == 201, created.text)
        # A saved version is a draft; dev auto-approve takes its publish request live, as a reviewer would.
        live = api.post("/v1/workflows/definitions/uc081_refund_check/publish-requests", json={}, headers=TEAM)
        check("its publish request is approved and the version is live", data(live)["status"] == "approved", live.text)

        # 1. No worker: the run is queued and stays queued.
        first = start_run(api, "uc081-a")
        time.sleep(2.0)
        queued = run_of(api, first)
        check("with no worker running the run stays queued", queued.get("status") == "queued", queued)

        # 2. A worker starts: the run reaches the review; the decision ends it.
        with worker("a"):
            waiting = until(status_is(api, first, "waiting"))
            check("a worker runs it to the human review", waiting is not None, run_of(api, first))
            events = sse(api.get(f"/v1/runs/{first}/events", params={"follow": "false"}, headers=TEAM).text)
            types = [e["type"] for e in events]
            check(
                "the run's events stream from the log: started, node steps, waiting_review",
                types[:1] == ["started"] and "node" in types and types[-1] == "waiting_review",
                types,
            )
            last = events[-1]["seq"] if events else 0
            again = sse(
                api.get(f"/v1/runs/{first}/events", params={"follow": "false", "after": last}, headers=TEAM).text
            )
            check("re-attaching after the last seq returns nothing old", again == [], again)
            review = api.get(f"/reviews/{first}", headers=MAYA)
            check(
                "the review is listed in Reviews, showing the looked-up customer",
                review.status_code == 200 and data(review)["proposal"] == "Marcus Bell",
                review.text[:300],
            )
            decided = api.post(f"/reviews/{first}/decision", json={"decision": "approved"}, headers=MAYA)
            check("a reviewer approves it", decided.status_code == 200, decided.text[:300])
            done = until(status_is(api, first, "succeeded", "failed"))
            check("the decision resumes the run to its approved end", (done or {}).get("outcome") == "approved", done)
        steps = {s["nodeId"]: s for s in run_of(api, first).get("steps", [])}
        check(
            "the run detail shows each step's input, output and port from the journal",
            steps.get("lookup", {}).get("port") == "ok"
            and steps["lookup"]["input"] == {"operation": "get_customer", "input": {"customer_id": "CUS-1001"}}
            and steps["lookup"]["output"]["name"] == "Marcus Bell"
            and steps.get("review", {}).get("port") == "approve",
            steps,
        )
        check("the first run called the tool once", len(tool_calls(gw, first)) == 1, tool_calls(gw, first))

        # 3. A worker killed right after the tool step's row is recorded; a new worker finishes the run.
        second = start_run(api, "uc081-b")
        with worker("b", {"OPS_ENGINE_FAULT_KILL_AFTER_NODE": "lookup"}) as doomed:
            code = until(doomed.poll, timeout=90)
        # `uv run` reports its child's SIGKILL as 128 + 9.
        check("the worker died by SIGKILL after the tool step", code in (-signal.SIGKILL, 128 + signal.SIGKILL), code)
        killed = run_of(api, second)
        recorded = [s for s in killed.get("steps", []) if s["nodeId"] == "lookup"]
        check(
            "the tool step's row was recorded before the kill and the run did not move on",
            bool(recorded) and recorded[0]["status"] == "ok" and killed.get("status") == "running",
            killed,
        )
        fault = {k: v for k, v in os.environ.items() if k == "OPS_ENGINE_FAULT_IGNORE_RECORDED"}
        with worker("c", fault):
            waiting = until(status_is(api, second, "waiting"), timeout=90)
            check("a new worker takes the run over and reaches the review", waiting is not None, run_of(api, second))
            decided = api.post(f"/reviews/{second}/decision", json={"decision": "rejected"}, headers=MAYA)
            check("a reviewer rejects it", decided.status_code == 200, decided.text[:300])
            done = until(status_is(api, second, "succeeded", "failed"))
            check("the run ends on its rejected end", (done or {}).get("outcome") == "rejected", done)
        calls = tool_calls(gw, second)
        check(
            "tools-service's executions show the tool called exactly once across the crash",
            len(calls) == 1,
            f"{len(calls)} calls: {[c.get('step') for c in calls]}",
        )
    finish()


if __name__ == "__main__":
    main()
