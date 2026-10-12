"""uc-042 a module's call counts come from real calls, api layer:
docs/usecases/tools-service/module-traffic-from-real-calls.md. Calls go through /v1/calls to the fake bank; the module
list, the module page and its activity read the call log."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from fake_bank_https import HOST, fake_bank
from usecase_harness import AGENTS_PORT, agents, check, data, finish, service_headers, tools

SECURITY = {"X-Dev-User": "Nadia Petrov"}
OTHER = {"X-Dev-User": "Priya Shah"}
RUN = int(time.time())
OK, FAILS, WRITES = f"get_account_{RUN}", f"get_missing_{RUN}", f"close_account_{RUN}"


def published_module(gw: Any, name: str, ops: list[dict[str, Any]]) -> str:
    made = data(gw.post("/v1/tool-modules/blank", json={"displayName": name, "name": name, "type": "http"}))
    for op in ops:
        gw.post(f"/v1/tool-modules/{made['id']}/operations", json=op)
    reviewed = data(gw.post(f"/v1/tool-modules/{made['id']}/reviews", json={"note": "uc-042"}))
    review = next(r["id"] for r in reviewed["reviews"] if r["decision"] == "pending")
    gw.post(f"/v1/tool-modules/{made['id']}/reviews/{review}/decide", json={"decision": "approved"}, headers=SECURITY)
    return str(made["id"])


def call(gw: Any, tool: str, step: str) -> int:
    body = {
        "tool": tool,
        "input": {"accountId": "CHQ-2219"},
        "key": f"{tool}-{step}",
        "runContext": {"thread": f"gth_uc042_{RUN}", "step": step, "act": "agent:uc042"},
    }
    return gw.post("/v1/calls", json=body, headers=service_headers("tools")).status_code


def row(gw: Any, module_id: str) -> dict[str, Any]:
    rows = data(gw.get("/v1/tool-modules", params={"pageSize": 100, "search": f"{RUN}"}))["data"]
    return next(r for r in rows if r["id"] == module_id)


def op(detail: dict[str, Any], name: str) -> dict[str, Any]:
    return next(o for o in detail["operations"] if o["name"] == name)


def approve(gw: Any, module_id: str, days: int) -> str:
    asked = gw.post(
        f"/v1/tool-modules/{module_id}/approvals",
        json={
            "workflowId": "dispute_email",
            "environment": "test",
            "operations": [OK],
            "expiresInDays": days,
            "justification": "Disputes read the account",
        },
    )
    decided = gw.post(
        f"/v1/tool-modules/{module_id}/approvals/{data(asked)['id']}/decide",
        json={"decision": "approved"},
        headers=OTHER,
    )
    return str(data(decided)["status"])


settings = {"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}
with fake_bank() as bank, agents(), tools(settings={**bank.settings, **settings}) as gw:
    gw.post("/v1/egress/hosts", json={"value": HOST, "note": "uc-042 fake bank"})
    gw.post("/v1/egress/ranges", json={"value": bank.range, "note": "uc-042 fake bank network"})
    url = f"https://{HOST}/v1"
    busy = published_module(
        gw,
        f"busy-{RUN}",
        [
            {"name": OK, "description": "", "access": "read", "method": "GET", "url": f"{url}/accounts/{{accountId}}"},
            {
                "name": FAILS,
                "description": "",
                "access": "read",
                "method": "GET",
                "url": f"{url}/missing/{{accountId}}",
            },
            {
                "name": WRITES,
                "description": "",
                "access": "write",
                "method": "POST",
                "url": f"{url}/accounts/{{accountId}}",
            },
        ],
    )
    quiet = published_module(
        gw,
        f"quiet-{RUN}",
        [
            {
                "name": f"get_quiet_{RUN}",
                "description": "",
                "access": "read",
                "method": "GET",
                "url": f"{url}/accounts/x",
            }
        ],
    )
    before = row(gw, busy)
    check(
        "a new module shows zero calls, errors and latency",
        (before["calls24h"], before["errorRate"], before["p95Ms"]) == (0, 0, 0),
        before,
    )

    statuses = [call(gw, OK, s) for s in ("a", "b", "c")] + [call(gw, FAILS, "d"), call(gw, WRITES, "e")]
    check(
        "three calls succeed, one fails upstream, a write without approval is refused",
        statuses[:4] == [200] * 4 and statuses[4] >= 400,
        statuses,
    )

    after = row(gw, busy)
    check(
        "the module row counts the four calls that ran, one in four failed, with a measured p95",
        after["calls24h"] == 4 and after["errorRate"] == 0.25 and after["p95Ms"] > 0,
        {k: after[k] for k in ("calls24h", "errorRate", "p95Ms")},
    )
    page = data(gw.get(f"/v1/tool-modules/{busy}"))
    counts = [(op(page, n)["calls24h"], op(page, n)["errorRate"]) for n in (OK, FAILS, WRITES)]
    check(
        "each operation counts its own calls; the refused write counts none", counts == [(3, 0), (1, 1), (0, 0)], counts
    )
    still = row(gw, quiet)
    check("a module nobody called stays at zero", still["calls24h"] == 0, still["calls24h"])

    activity = data(gw.get(f"/v1/tool-modules/{busy}/activity"))
    today = datetime.now(UTC).date().isoformat()
    days = {d["date"]: (d["count"], d["errors"]) for d in activity["days"]}
    check(
        "the activity chart's today is the four calls and the other thirteen days are empty",
        len(days) == 14 and days.get(today) == (4, 1) and sum(c for c, _ in days.values()) == 4,
        days,
    )
    check("the refused write is counted as denied", activity["denied24h"] == 1, activity["denied24h"])

    month = approve(gw, busy, 30)
    state = row(gw, busy)["approvalState"]
    check(
        "a 30-day approval granted today is approved, not expiring",
        month == "approved" and state == "approved",
        [month, state],
    )
    approve(gw, busy, 5)
    check("an approval with five days left makes the module expiring", row(gw, busy)["approvalState"] == "expiring")

finish()
