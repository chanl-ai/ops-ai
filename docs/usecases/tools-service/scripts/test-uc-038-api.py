"""uc-038 a failed tool call says which side failed, and a test call reaches the real system, api layer:
docs/usecases/tools-service/failure-side-and-real-reads.md.

Live: it calls https://postman-echo.com through the gateway, so it runs only with OPS_LIVE_EGRESS=1 and reports
skipped otherwise (offline CI). It passes when the request reached the upstream and the upstream's status is reported
as the upstream's (a 5xx counts as "reached, the upstream failed"); a connect or TLS failure on our side fails it.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any

from usecase_harness import AGENTS_PORT, agents, check, data, finish, service_headers, tools

LIVE = os.environ.get("OPS_LIVE_EGRESS") == "1"
RUN = int(time.time())
ECHO = "postman-echo.com"
# A name under the reserved .invalid TLD never resolves: an allowed host whose call fails on our side.
NOWHERE = f"nowhere-{RUN}.invalid"
SECURITY = {"X-Dev-User": "Nadia Petrov"}
OTHER = {"X-Dev-User": "Priya Shah"}


def module(gw: Any, host: str, name: str) -> tuple[str, str]:
    """A published module on `host` with one read, GET /get; returns (module id, tool name)."""
    gw.post("/v1/egress/hosts", json={"value": host, "note": "uc-038"})
    made = data(gw.post("/v1/tool-modules/blank", json={"displayName": name, "name": f"{name}-{RUN}", "type": "http"}))
    tool = f"echo_{name}_{RUN}"
    op = {
        "name": tool,
        "description": "Echo the order",
        "access": "read",
        "method": "GET",
        "url": f"https://{host}/get",
    }
    added = gw.post(f"/v1/tool-modules/{made['id']}/operations", json=op)
    if added.status_code != 200:
        raise SystemExit(f"FAIL setup: adding {tool} answered {added.status_code}: {added.text[:300]}")
    asked = gw.post(f"/v1/tool-modules/{made['id']}/reviews", json={"note": "uc-038"})
    if asked.status_code != 200:
        raise SystemExit(f"FAIL setup: the first review answered {asked.status_code}: {asked.text[:300]}")
    reviewed = data(asked)
    review = next(r["id"] for r in reviewed["reviews"] if r["decision"] == "pending")
    gw.post(f"/v1/tool-modules/{made['id']}/reviews/{review}/decide", json={"decision": "approved"}, headers=SECURITY)
    return made["id"], tool


def call(gw: Any, tool: str, step: str) -> dict[str, Any]:
    body = {
        "tool": tool,
        "input": {},
        "key": f"{tool}-{step}",
        "runContext": {"thread": f"gth_uc038_{RUN}", "step": step, "act": "agent:uc038"},
    }
    r = gw.post("/v1/calls", json=body, headers=service_headers("tools"))
    return {"http": r.status_code, **(r.json().get("data") or {})}


def reached(result: dict[str, Any]) -> bool:
    """The request reached the upstream: it answered (ok), or it answered or stalled after connecting (its side)."""
    error = (result.get("output") or {}).get("error") if not result.get("ok") else None
    return bool(result.get("ok")) or (isinstance(error, dict) and error.get("side") == "upstream")


if not LIVE:
    check("skipped: OPS_LIVE_EGRESS=1 is not set, so nothing was called", True)
    finish()

# Approvals name agents-service's workflows, so tools-service reads them from a running agents-service.
with agents(), tools(settings={"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}) as gw:
    echo_id, echo_tool = module(gw, ECHO, "echo")
    live = call(gw, echo_tool, "s1")
    error = (live.get("output") or {}).get("error") or {}
    check(
        f"a call through /v1/calls reached {ECHO} and its answer is reported as the upstream's",
        live.get("decision") == "allow" and reached(live),
        live,
    )
    if live.get("ok"):
        check(
            "the upstream echoed the request the gateway sent",
            f"{ECHO}/get" in str(live["output"].get("url")),
            live,
        )
        # postman-echo sets session cookies on every answer; the gateway's shared client must never send them back.
        again = call(gw, echo_tool, "s1b")
        echoed = {k.lower() for k in ((again.get("output") or {}).get("headers") or {})}
        check(
            "a second call carries no cookie from the first (the egress client keeps none)",
            bool(again.get("ok")) and "cookie" not in echoed,
            again,
        )
    else:
        check(
            "an upstream failure keeps the upstream's status",
            error.get("side") == "upstream" and "status" in error,
            error,
        )

    nowhere_id, nowhere_tool = module(gw, NOWHERE, "nowhere")
    failed = call(gw, nowhere_tool, "s2")
    lost = (failed.get("output") or {}).get("error") or {}
    check(
        "an allowed host that cannot be reached fails on our side, named as such",
        (lost.get("code"), lost.get("side")) == ("CONNECT_FAILED", "ours"),
        failed,
    )
    rows = data(gw.get("/v1/executions", params={"thread": f"gth_uc038_{RUN}", "pageSize": 10})).get("data", [])
    by_step = {r.get("step"): r for r in rows}
    check(
        "the executions log shows the side each failure broke on",
        by_step.get("s2", {}).get("failureSide") == "ours"
        and by_step.get("s2", {}).get("errorCode") == "CONNECT_FAILED",
        rows,
    )
    messages = [str(r.get("errorMessage") or "") for r in rows] + [str(lost.get("message") or "")]
    check(
        "no failure message carries a dialled address",
        not any(re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", m) for m in messages),
        messages,
    )

    # The test console's "Test environment" makes the same real read, as a workflow approved for the module.
    approval = {
        "workflowId": "dispute_email",
        "environment": "production",
        "operations": [echo_tool],
        "expiresInDays": 30,
        "justification": "The dispute workflow reads the echo to check the live egress path",
    }
    requested = gw.post(f"/v1/tool-modules/{echo_id}/approvals", json=approval)
    if requested.status_code != 201:
        raise SystemExit(f"FAIL setup: the approval request answered {requested.status_code}: {requested.text[:300]}")
    asked = data(requested)
    gw.post(f"/v1/tool-modules/{echo_id}/approvals/{asked['id']}/decide", json={"decision": "approved"}, headers=OTHER)
    contexts = data(gw.get(f"/v1/tool-modules/{echo_id}"))["runContexts"]
    body = {"operation": echo_tool, "contextId": contexts[0]["id"], "target": "sandbox", "input": {}}
    panel = data(gw.post(f"/v1/tool-modules/{echo_id}/test", json=body))
    check(
        f"the test console's Test environment read reached {ECHO}, not the stub",
        panel.get("stubbed") is False and panel.get("reachedHost") == ECHO and panel.get("latencyMs", 0) > 0,
        panel,
    )

finish()
