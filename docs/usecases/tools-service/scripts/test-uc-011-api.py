"""uc-011 a tool call runs through the registry and is logged with its caller, api layer:
docs/usecases/tools-service/calls-through-the-registry.md."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from usecase_harness import ROOT, check, data, finish, service_headers, tools

THREAD = f"uc011_{int(time.time())}"
# OPA admits only identities registered in its data (services/tools-service/policy/data.json).
CONTEXT = {"thread": THREAD, "act": "agent:dispute_triage"}
ADDRESS = {
    "customerId": "CUS-118842",
    "line1": "12 Elm St",
    "city": "Halifax",
    "province": "NS",
    "postalCode": "B3H 1A1",
}


TRANSFER = {"fromAccount": "CHQ-2219", "toAccount": "SAV-7710", "memo": "uc-011"}
MOCK_RULE = Path(ROOT) / "apps" / "console" / "src" / "lib" / "api" / "mock" / "tool-modules" / "amount.ts"


def mock_refuses(amount_max: float, cases: list[dict[str, Any]]) -> list[bool]:
    """The console mock's amount rule on each case, run by node from the file the mock imports."""
    js = (
        f"const m = await import({json.dumps(MOCK_RULE.as_uri())});"
        f"const o = {{amountMax: {amount_max}, input: [{{name: 'amount'}}]}};"
        f"console.log(JSON.stringify({json.dumps(cases)}.map((a) => m.amountRefused(o, a))));"
    )
    out = subprocess.run(["node", "--input-type=module", "-e", js], capture_output=True, text=True, check=True)
    return list(json.loads(out.stdout.strip().splitlines()[-1]))


def call(gw: Any, tool: str, args: dict[str, Any], step: str) -> Any:
    body = {"tool": tool, "input": args, "key": step, "runContext": {**CONTEXT, "step": step}}
    return gw.post("/v1/calls", json=body, headers=service_headers("tools"))


with tools() as gw:
    read = call(gw, "get_loan_account", {"loanAccountId": "LN-0048213"}, "s1")
    output = data(read).get("output", {}) if read.status_code == 200 else {}
    check(
        "a registry read runs (200)",
        read.status_code == 200 and output.get("loanAccountId") == "LN-0048213",
        read.text[:200],
    )
    check("masked fields stay masked", output.get("borrower", {}).get("sin") == "[redacted]", output)

    write = call(gw, "update_address", ADDRESS, "s2")
    check("a registry write without an approval token is refused (403)", write.status_code == 403, write.text[:200])

    bad = call(gw, "get_loan_account", {"include": ["schedule"]}, "s3")
    invalid = bad.json().get("error", {}).get("details", {}).get("invalid") if bad.status_code == 422 else None
    check(
        "input missing a required field is refused before egress (422)",
        invalid == [{"field": "loanAccountId", "message": "Required."}],
        bad.text[:200],
    )

    unknown = call(gw, "drop_tables", {}, "s4")
    check("a tool no module holds is refused (403)", unknown.status_code == 403, unknown.text[:200])

    rows = data(gw.get("/v1/executions", params={"thread": THREAD, "pageSize": 10})).get("data", [])
    by_step = {r.get("step"): r for r in rows}
    check("every call is logged, refused ones too", sorted(by_step) == ["s1", "s2", "s3", "s4"], sorted(by_step))
    first = by_step.get("s1", {})
    check(
        "the log names the calling service (from its token), the agent, and the run",
        first.get("subject", {}).get("id") == "service:agents"
        and first.get("actor", {}).get("id") == "dispute_triage"
        and first.get("runId") == THREAD,
        first,
    )
    check(
        "refusals are logged as denied",
        [by_step.get(s, {}).get("status") for s in ("s2", "s3", "s4")] == ["denied"] * 3,
        rows,
    )

    # c-028: the operation's limits hold on real calls.
    bank = data(gw.get("/v1/tool-modules/mod_core_banking"))
    loan = next(o for o in bank["operations"] if o["name"] == "get_loan_account")
    limited = gw.patch(f"/v1/tool-modules/mod_core_banking/operations/{loan['id']}", json={"rateLimitPerMin": 1})
    check("the rate limit is set to one call a minute", limited.status_code == 200, limited.text[:200])
    tries = [call(gw, "get_loan_account", {"loanAccountId": "LN-0048213"}, f"r{i}") for i in range(3)]
    refused = [(f"r{i}", r) for i, r in enumerate(tries) if r.status_code == 429]
    check(
        "a call past the operation's rate limit is refused RATE_LIMITED with its reset time",
        bool(refused)
        and all(
            r.json()["error"]["code"] == "RATE_LIMITED" and r.json()["error"]["details"].get("resetAt")
            for _, r in refused
        ),
        [r.status_code for r in tries],
    )
    transfer = next(o for o in bank["operations"] if o["name"] == "transfer_funds")
    shown = gw.patch(
        f"/v1/tool-modules/mod_core_banking/operations/{transfer['id']}", json={"enabled": True, "binding": None}
    )
    check(
        "transfer_funds (seeded hidden and bound to a case) is shown and unbound so it can be called",
        shown.status_code == 200,
        shown.text[:200],
    )
    over = call(gw, "transfer_funds", {**TRANSFER, "amount": 3000}, "a1")
    check(
        "a money call over its amount limit is refused before the policy (403 amount_over_limit)",
        over.status_code == 403 and over.json()["error"]["code"] == "amount_over_limit",
        over.text[:200],
    )
    logged = {
        r.get("step"): r
        for r in data(gw.get("/v1/executions", params={"thread": THREAD, "pageSize": 20})).get("data", [])
    }
    check(
        "rate and amount refusals are logged as denied",
        all(logged.get(step, {}).get("status") == "denied" for step in [s for s, _ in refused] + ["a1"]),
        sorted(logged),
    )
    panel = gw.post(
        "/v1/tool-modules/mod_core_banking/test",
        json={
            "operation": "transfer_funds",
            "contextId": "owner",
            "target": "stub",
            "input": {**TRANSFER, "amount": 3000},
        },
    )
    check(
        "the test panel refuses the same amount the gateway refused",
        panel.status_code == 200 and data(panel).get("denyReason") == "constraint",
        panel.text[:200],
    )
    cases: list[dict[str, Any]] = [{"amount": 3000}, {"amount": 2500}, {"amount": 100}, {"amount": "abc"}, {}, {"amount": -5000000}]
    gateway = []
    for i, case in enumerate(cases):
        r = call(gw, "transfer_funds", {**TRANSFER, **case}, f"p{i}")
        gateway.append(r.json().get("error", {}).get("code") in ("amount_over_limit", "invalid_input"))
    check(
        "the console mock refuses exactly the amounts the gateway refuses",
        mock_refuses(2500, cases) == gateway == [True, False, False, True, True, True],
        {"gateway": gateway},
    )

finish()
