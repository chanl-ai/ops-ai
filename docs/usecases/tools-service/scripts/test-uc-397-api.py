"""uc-397 a workflow's tool step reaches its error and timeout ports on mock answers in a test run, and the same
workflow live reaches the system, api layer: docs/usecases/tools-service/mock-answers.md. tools-service with the core
bank stand-in, agents-service and a worker. No model call."""

from __future__ import annotations

import time
from contextlib import ExitStack
from typing import Any

import httpx
from connection_calls import allow_bank, clean, connection, module
from usecase_harness import AGENTS_PORT, TOOLS_PORT, agents, check, core_bank, data, engine_worker, finish, tools

OPS = {"X-Team-Id": "team_ops"}
OP = "uc397_get_account"
FLOW = {
    "schemaVersion": 2,
    "id": "uc397_lookup",
    "name": "Look up an account",
    "nodes": [
        {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
        {
            "id": "lookup",
            "type": "ops.action.tool",
            "typeVersion": 1,
            "parameters": {"operation": OP, "input": {"account_id": "$.input.account"}, "onTimeout": "port"},
        },
        {"id": "found", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "found"}},
        {"id": "held", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "held"}},
        {"id": "failed", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "failed"}},
        {"id": "late", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "timed_out"}},
    ],
    "connections": [
        {"from": {"node": "start", "port": "payload"}, "to": {"node": "lookup", "port": "in"}},
        {"from": {"node": "lookup", "port": "ok"}, "to": {"node": "found", "port": "in"}},
        {"from": {"node": "lookup", "port": "refused"}, "to": {"node": "held", "port": "in"}},
        {"from": {"node": "lookup", "port": "error"}, "to": {"node": "failed", "port": "in"}},
        {"from": {"node": "lookup", "port": "timeout"}, "to": {"node": "late", "port": "in"}},
    ],
}


def run(api: httpx.Client, mode: str, account: str) -> dict[str, Any]:
    body = {"workflowId": FLOW["id"], "mode": mode, "input": {"account": account}}
    started = data(api.post("/v1/runs", json=body, headers=OPS)) or {}
    deadline = time.monotonic() + 120
    while started.get("runId") and time.monotonic() < deadline:
        detail = data(api.get(f"/v1/runs/{started['runId']}", headers=OPS))
        if detail["status"] in ("succeeded", "failed", "cancelled"):
            step = next((s for s in detail["steps"] if s.get("nodeId") == "lookup"), {})
            return {"outcome": detail.get("outcome"), "output": step.get("output")}
        time.sleep(0.5)
    return {"outcome": "did not finish", "started": started}


with ExitStack() as stack:
    bank = stack.enter_context(core_bank())
    gw = stack.enter_context(tools({**bank["settings"], "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}))
    gateway = f"http://127.0.0.1:{TOOLS_PORT}"
    api = stack.enter_context(agents(gateway_url=gateway))
    stack.enter_context(engine_worker("uc397", {"OPS_GATEWAY_URL": gateway}))
    BANK_BASE = f"https://{bank['host']}"  # the stand-in's address, which its credentials are bound to
    clean(gw, "uc397")
    allow_bank(gw, bank)
    key = {"settings": {"name": "X-Api-Key"}, "secretValues": {"key": "dev-bank-key"}}
    conn = connection(gw, "uc397 core banking", "api_key", {"test": key, "production": key}, base_url=BANK_BASE)
    made = module(gw, "uc397-get-account", f"https://{bank['host']}/accounts/{{account_id}}", conn["id"])
    op = made["operations"][0]
    base = f"/v1/tool-modules/{made['id']}/operations/{op['id']}/mocks"
    # A short limit keeps the timeout mock quick; a real call answers well inside it.
    gw.patch(f"/v1/tool-modules/{made['id']}/operations/{op['id']}", json={"timeoutMs": 1500})

    # 1. A builder sets the operation's mock answers: an error, a timeout, and a default sample.
    mocks = [
        {
            "name": "Core banking down",
            "match": {"account_id": "ERR-1"},
            "status": 503,
            "body": {"error": "maintenance"},
        },
        {"name": "Core banking slow", "match": {"account_id": "SLOW-1"}, "timeout": True},
        {"name": "Sample account", "default": True, "body": {"id": "CHQ-2219", "balance": 1.0, "status": "mock"}},
    ]
    added = [gw.post(base, json=m) for m in mocks]
    check(
        "1 the three mock answers are added (201)",
        all(r.status_code == 201 for r in added),
        [r.text[:120] for r in added],
    )
    listed = data(gw.get(base))
    check(
        "1 they are listed in order, the sample the default",
        [m["name"] for m in listed["data"]] == [m["name"] for m in mocks] and listed["data"][2]["default"],
        listed,
    )
    saved = api.post("/v1/workflows/definitions", json={"definition": FLOW}, headers=OPS)
    live = api.post(f"/v1/workflows/definitions/{FLOW['id']}/publish-requests", json={}, headers=OPS)
    check(
        "1 the workflow with a timeout port saves and goes live",
        saved.status_code == 201 and (data(live) or {}).get("status") == "approved",
        (saved.text[:300], live.text[:300]),
    )

    # 2. A test run on the error mock leaves by the error port; on the timeout mock by the timeout port.
    failed = run(api, "test", "ERR-1")
    check(
        "2 a test run on the error mock leaves by its error port",
        failed["outcome"] == "failed" and "503" in str(failed.get("output")),
        failed,
    )
    late = run(api, "test", "SLOW-1")
    check(
        "2 a test run on the timeout mock leaves by its timeout port",
        late["outcome"] == "timed_out" and "UPSTREAM_TIMEOUT" in str(late.get("output")),
        late,
    )
    sample = run(api, "test", "CHQ-2219")
    check(
        "2 a test run with no matching mock gets the default sample",
        sample["outcome"] == "found" and (sample.get("output") or {}).get("status") == "mock",
        sample,
    )

    # 3. The same workflow live reaches the system: no mock answers a live run.
    real = run(api, "live", "CHQ-2219")
    out = real.get("output") or {}
    check(
        "3 a live run reaches the bank, not the sample",
        real["outcome"] == "found" and out.get("id") == "CHQ-2219" and out.get("status") != "mock",
        real,
    )
    rows = data(gw.get("/v1/executions", params={"tool": OP, "pageSize": 20}))["data"]
    check(
        "3 the call log names each call's environment",
        sorted({r.get("environment") for r in rows}) == ["production", "test"],
        [(r.get("environment"), r.get("status")) for r in rows],
    )
finish()
