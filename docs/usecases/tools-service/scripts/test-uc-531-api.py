"""uc-531 a builder adds a Python function tool that runs sandboxed and uses a secret, api layer:
docs/usecases/tools-service/a-builder-adds-a-python-function-tool.md."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import httpx
from fake_bank_https import HOST, fake_bank
from usecase_harness import (
    TEAM,
    TOOLS_PORT,
    agents,
    approve_tool_review,
    check,
    data,
    engine_worker,
    finish,
    runner,
    service_headers,
    tools,
    until,
)

# A Security reviewer, acting in the Security team: deciding a module review needs a reviewer of that team.
SECURITY = {"X-Dev-User": "Nadia Petrov", "X-Team-Id": "team_security"}
SECRET = "UC531_KEY"
VALUE = f"sk-uc531-{int(time.time())}"
FUNCTION = "uc531_check_card_limit"
ACCOUNT, LIMITS = "uc531_get_account", "uc531_get_limits"

SOURCE = f'''
def main(input):
    mode = input.get("mode", "check")
    if mode == "unbound":
        return ops.call("uc531_delete_everything", {{}})
    if mode == "socket":
        import socket
        socket.socket().connect(("1.1.1.1", 443))
    if mode == "loop":
        while True:
            pass
    if mode == "memory":
        return len(bytearray(600 << 20))
    account = ops.call("{ACCOUNT}", {{"accountId": input["accountId"]}})
    limits = ops.call("{LIMITS}", {{"rulesKey": ops.secret("{SECRET}")}})
    left = limits["dailyLimit"] - limits["spentToday"]
    print("left today", left)
    return {{
        "overLimit": input["amount"] > left,
        "leftToday": left,
        "balance": account["balance"],
        "keyFingerprint": limits["keyFingerprint"],
        "echo": limits["echo"],
    }}
'''


# A workflow whose tool step runs the function and whose If step branches on the JSON it returns (US1).
WORKFLOW = f"""
schemaVersion: 2
id: uc531_card_check
name: Card limit check (uc-531)
nodes:
  - {{id: start, type: ops.trigger.request, typeVersion: 1, name: Spend}}
  - id: check
    type: ops.action.tool
    typeVersion: 1
    name: Check the limit
    parameters: {{operation: {FUNCTION}, input: {{accountId: "$.input.accountId", amount: "$.input.amount"}}}}
  - id: over
    type: ops.flow.if
    typeVersion: 1
    name: Over the limit?
    parameters: {{conditions: [{{left: "$.nodes.check.out.overLimit", op: eq, right: true}}], combine: any}}
  - {{id: refuse, type: ops.flow.end, typeVersion: 1, name: Refuse, parameters: {{outcome: over_limit}}}}
  - {{id: allow, type: ops.flow.end, typeVersion: 1, name: Allow, parameters: {{outcome: within_limit}}}}
  - {{id: failed, type: ops.flow.end, typeVersion: 1, name: Failed, parameters: {{outcome: check_failed}}}}
connections:
  - {{from: {{node: start, port: payload}}, to: {{node: check, port: in}}}}
  - {{from: {{node: check, port: ok}}, to: {{node: over, port: in}}}}
  - {{from: {{node: check, port: error}}, to: {{node: failed, port: in}}}}
  - {{from: {{node: check, port: refused}}, to: {{node: failed, port: in}}}}
  - {{from: {{node: over, port: "true"}}, to: {{node: refuse, port: in}}}}
  - {{from: {{node: over, port: "false"}}, to: {{node: allow, port: in}}}}
"""


def outcome(api: httpx.Client, key: str, amount: float) -> str | None:
    body = {"workflowId": "uc531_card_check", "input": {"accountId": "A1", "amount": amount}, "runKey": key}
    run_id = str((data(api.post("/v1/runs", json=body, headers=TEAM)) or {}).get("runId"))

    def ended() -> dict[str, Any] | None:
        run = data(api.get(f"/v1/runs/{run_id}", headers=TEAM)) or {}
        return run if run.get("status") in ("succeeded", "failed") else None

    return (until(ended) or {}).get("outcome")


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def call(gw: httpx.Client, **input: Any) -> httpx.Response:
    body = {
        "tool": FUNCTION,
        "input": input,
        "key": f"uc531-{input.get('mode', 'check')}-{time.time_ns()}",
        "runContext": {"act": "workflow:dispute_email"},
    }
    return gw.post("/v1/calls", json=body, headers=service_headers("tools"))


def error_code(r: httpx.Response) -> str | None:
    out = data(r) or {}
    return ((out.get("output") or {}).get("error") or {}).get("code")


def remove_modules(gw: httpx.Client) -> None:
    for m in data(gw.get("/v1/tool-modules", params={"search": "uc531", "pageSize": 50}))["data"]:
        gw.delete(f"/v1/tool-modules/{m['id']}")


def publish(gw: httpx.Client, module_id: str) -> None:
    data(gw.post(f"/v1/tool-modules/{module_id}/reviews", json={"note": "uc-531"}, headers=TEAM))
    approve_tool_review(gw, module_id, SECURITY)


with (
    fake_bank() as bank,
    agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}") as api,
    runner() as runner_url,
    tools(settings={**bank.settings, "OPS_RUNNER_URL": runner_url}) as gw,
):
    remove_modules(gw)
    gw.delete(f"/v1/secrets/{SECRET}")
    gw.post("/v1/egress/hosts", json={"value": HOST})
    gw.post("/v1/egress/ranges", json={"value": bank.range})

    # The bank system: an account read, and a limits read that takes its key as a query value.
    http_op = {
        "name": ACCOUNT,
        "description": "An account's balance",
        "access": "read",
        "method": "GET",
        "url": f"https://{HOST}/v1/accounts/{{accountId}}",
    }
    body = {"name": "uc531-bank", "displayName": "uc531 Bank", "system": "Bank", "type": "http", "endpoint": ""}
    # Both modules belong to the team the workflow below runs in, as a builder of that team would make them.
    bank_module = data(gw.post("/v1/tool-modules", json={**body, "http": http_op}, headers=TEAM))
    limits_op = {**http_op, "name": LIMITS, "description": "A card's daily limit", "url": f"https://{HOST}/v1/limits"}
    bank_module = data(gw.post(f"/v1/tool-modules/{bank_module['id']}/operations", json=limits_op, headers=TEAM))
    op_id = next(o["id"] for o in bank_module["operations"] if o["name"] == LIMITS)
    field = {"name": "rulesKey", "type": "string", "required": True}
    data(gw.patch(f"/v1/tool-modules/{bank_module['id']}/operations/{op_id}", json={"input": [field]}, headers=TEAM))
    publish(gw, bank_module["id"])
    gw.post("/v1/secrets", json={"name": SECRET, "value": VALUE}, headers=TEAM)

    # The builder's function: bound to the two reads and the secret, with a 2 s and 128 MB limit.
    function = {
        "name": FUNCTION,
        "description": "Says whether a spend would pass the card's daily limit",
        "access": "read",
        "input": [
            {"name": "accountId", "type": "string", "required": False},
            {"name": "amount", "type": "number", "required": False},
            {"name": "mode", "type": "string", "required": False},
        ],
        "code": {
            "source": SOURCE,
            "bindings": [ACCOUNT, LIMITS],
            "secrets": [SECRET],
            "limits": {"memoryMb": 128, "timeS": 2, "calls": 5},
        },
    }
    made = gw.post(
        "/v1/tool-modules",
        json={"name": "uc531-checks", "displayName": "uc531 Checks", "system": "Card checks", "type": "code",
              "endpoint": "", "function": function},
        headers=TEAM,
    )  # fmt: skip
    check("a code module is created with its function (201)", made.status_code == 201, made.text[:300])
    code_module = data(made) or {}
    stored = next((o for o in code_module.get("operations", []) if o["name"] == FUNCTION), {})
    check(
        "the function is stored with its bindings and secret names",
        stored.get("executor") == "code" and stored.get("code", {}).get("secrets") == [SECRET],
        stored.get("code"),
    )
    publish(gw, code_module["id"])

    ran = call(gw, accountId="A1", amount=950)
    out = (data(ran) or {}).get("output") or {}
    check(
        "the function runs in the sandbox and returns JSON a step can branch on",
        ran.status_code == 200 and out.get("overLimit") is True and out.get("leftToday") == 900,
        ran.text[:400],
    )
    check("its bound account read ran as a gateway call", out.get("balance") == 1200.5, out)
    limits_calls = [r for r in bank.received if r["path"].startswith("/v1/limits")]
    check(
        "the bank received the secret's value, put in by the gateway from the handle",
        out.get("keyFingerprint") == fingerprint(VALUE) and len(limits_calls) == 1,
        out.get("keyFingerprint"),
    )
    check(
        "the bank echoing the key back reaches the function scrubbed",
        out.get("echo") == "[secret]" and VALUE not in ran.text,
        out.get("echo"),
    )
    logged = gw.get("/v1/executions", params={"pageSize": 50})
    rows = json.dumps(data(logged))
    check(
        "the call log holds the function's call and each bound call, and no secret value",
        logged.status_code == 200 and FUNCTION in rows and LIMITS in rows and VALUE not in rows,
        logged.status_code,
    )

    unbound = call(gw, mode="unbound")
    refused = error_code(unbound) == "binding_forbidden"
    check("a tool the function is not bound to is refused", refused, unbound.text[:300])
    sock = call(gw, mode="socket")
    check(
        "opening a socket fails inside the sandbox",
        error_code(sock) == "function_error" and "OSError" in sock.text,
        sock.text[:300],
    )
    loop = call(gw, mode="loop")
    check("a loop past its 2 s limit is stopped", error_code(loop) == "time_limit", loop.text[:300])
    big = call(gw, mode="memory")
    check("memory past its 128 MB cap is stopped", error_code(big) == "memory_limit", big.text[:300])

    saved = api.post("/v1/workflows/definitions", json={"yaml": WORKFLOW}, headers=TEAM)
    live = api.post("/v1/workflows/definitions/uc531_card_check/publish-requests", json={}, headers=TEAM)
    check(
        "a workflow with the function as a tool step goes live",
        (data(live) or {}).get("status") == "approved",
        saved.text[:300],
    )
    with engine_worker("uc531", {"OPS_GATEWAY_URL": f"http://127.0.0.1:{TOOLS_PORT}"}):
        over, within = outcome(api, f"uc531-wf-{time.time_ns()}", 950), outcome(api, f"uc531-wf-{time.time_ns()}", 100)
    check(
        "the step's If branches on the function's output: 950 refused, 100 allowed",
        (over, within) == ("over_limit", "within_limit"),
        (over, within),
    )

    remove_modules(gw)
    gw.delete(f"/v1/secrets/{SECRET}")

finish()
