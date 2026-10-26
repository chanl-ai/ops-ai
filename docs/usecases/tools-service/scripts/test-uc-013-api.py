"""uc-013 a tool's credential is a secret that never comes back, api layer: docs/usecases/tools-service/secrets.md."""

from __future__ import annotations

import hashlib
import time
from typing import Any

import httpx
from fake_bank_https import HOST, fake_bank
from usecase_harness import agents, approve_tool_review, check, data, finish, service_headers, tools

SECURITY = {"X-Dev-User": "Nadia Petrov", "X-Team-Id": "team_security"}
NAME = "STATEMENTS_KEY"
VALUE = f"sk-uc013-{int(time.time())}"
ROTATED = f"{VALUE}-rotated"


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:12]


def call(gw: httpx.Client) -> httpx.Response:
    body = {"tool": "latest_statement", "input": {}, "key": "uc013", "runContext": {"act": "workflow:dispute_email"}}
    return gw.post("/v1/calls", json=body, headers=service_headers("tools"))


def statement_requests(bank: Any) -> list[dict[str, Any]]:
    return [r for r in bank.received if r["path"] == "/v1/statements/latest"]


with fake_bank() as bank, agents(), tools(settings=bank.settings) as gw:
    for m in data(gw.get("/v1/tool-modules", params={"search": "uc013", "pageSize": 50}))["data"]:
        gw.delete(f"/v1/tool-modules/{m['id']}")
    gw.delete(f"/v1/secrets/{NAME}")
    gw.post("/v1/egress/hosts", json={"value": HOST})
    gw.post("/v1/egress/ranges", json={"value": bank.range})
    spec = {"kind": "openapi", "specUrl": f"https://{HOST}/v1/openapi.json"}
    op = {"name": "latest_statement", "description": "", "access": "read", "group": "statements", "input": []}
    body = {
        "name": "uc013-statements",
        "displayName": "Statements",
        "system": "Statements",
        "type": "openapi",
        "endpoint": "",
        "connectionId": "int_core_banking",
        "operations": [op],
        "source": spec,
    }
    module = data(gw.post("/v1/tool-modules", json=body))
    data(gw.post(f"/v1/tool-modules/{module['id']}/reviews", json={"note": "uc-013"}))
    approve_tool_review(gw, module["id"], SECURITY)

    missing = call(gw)
    check(
        "without its secret the call is refused and nothing is sent",
        "SECRET_MISSING" in missing.text and not statement_requests(bank),
        missing.text[:200],
    )

    made = gw.post("/v1/secrets", json={"name": NAME, "value": VALUE})
    listed = gw.get("/v1/secrets")
    check(
        "the secret is created (201) and its value is in neither answer",
        made.status_code == 201 and VALUE not in made.text + listed.text,
        made.text[:200],
    )

    first = call(gw)
    out = data(first).get("output", {}) if first.status_code == 200 else {}
    check("the call carries the secret to the bank", out.get("keyFingerprint") == fingerprint(VALUE), first.text[:300])
    check(
        "the bank echoing the header back does not return the value",
        VALUE not in first.text and out.get("echo", {}).get("X-Api-Key") == "[secret]",
        out.get("echo"),
    )

    gw.post(f"/v1/secrets/{NAME}/rotate", json={"value": ROTATED})
    second = call(gw)
    check(
        "after a rotation the next call carries the new value",
        data(second).get("output", {}).get("keyFingerprint") == fingerprint(ROTATED),
        second.text[:300],
    )

    executions = gw.get("/v1/executions", params={"tool": "latest_statement", "pageSize": 20})
    check(
        "the executions log holds neither value",
        executions.status_code == 200 and VALUE not in executions.text and ROTATED not in executions.text,
        executions.status_code,
    )

    for m in data(gw.get("/v1/tool-modules", params={"search": "uc013", "pageSize": 50}))["data"]:
        gw.delete(f"/v1/tool-modules/{m['id']}")
    gone = gw.delete(f"/v1/secrets/{NAME}")
    check("the secret is deleted (204)", gone.status_code == 204, gone.text[:200])

finish()
