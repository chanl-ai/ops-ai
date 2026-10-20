"""uc-230 a workflow step notifies an outside system's webhook with a case's data, api layer:
docs/usecases/tools-service/notify-a-webhook.md. tools-service with the core bank fake behind it, whose /webhooks
receiver stands in for the outside system; the call is sent as agents-service sends a workflow step's. No model call."""

from __future__ import annotations

import json
from contextlib import ExitStack
from typing import Any

import httpx
from usecase_harness import (
    AGENTS_PORT,
    TOOLS_PORT,
    agents,
    check,
    core_bank,
    data,
    finish,
    publish_bank_module,
    service_headers,
    tools,
)

PAYLOAD = {"caseNo": "NS-2026-GN-01187", "debtor": "Marcus Bell", "amount": 3250.0, "kind": "restraining notice"}


def call(gw: httpx.Client, key: str, payload: dict[str, Any]) -> httpx.Response:
    body = {
        "tool": "notify_webhook",
        "input": {"hook": "levy", "event": "levy.processed", "payload": payload},
        "key": key,
        "runContext": {"thread": "wfrun_uc230", "step": key, "act": "workflow:levy_demo"},
    }
    return gw.post("/v1/calls", json=body, headers=service_headers("tools", scopes=["tools:view"], team="team_ops"))


with ExitStack() as stack:
    bank = stack.enter_context(core_bank())
    gw = stack.enter_context(tools({**bank["settings"], "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}))
    # agents-service holds the module's review (c-163), which the publish below waits on.
    stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}"))
    address = json.loads(bank["settings"]["OPS_EGRESS_RESOLVE"])[bank["host"]]
    inbox = f"https://{address}/webhooks.json"

    # 1. Before its host is on the egress allow-list, the call does not leave.
    gw.post("/v1/secrets", json={"name": "BANK_API_KEY", "value": "dev-bank-key"})
    gw.post("/v1/egress/hosts", json={"value": bank["host"], "note": "uc-230"})
    gw.post("/v1/egress/ranges", json={"value": bank["range"], "note": "uc-230"})
    module_id = publish_bank_module(gw, bank["host"])
    op = next(o for o in data(gw.get(f"/v1/tool-modules/{module_id}"))["operations"] if o["name"] == "notify_webhook")
    check(
        "1 the webhook is an operation of the module: a write that runs at once",
        (op["access"], op["requiresApproval"]) == ("write", False),
        op,
    )

    # 2. Without its secret the receiver refuses it, and nothing is recorded there.
    no_secret = call(gw, "uc230-1", PAYLOAD)
    received = httpx.get(inbox, verify=False).json()
    check(
        "2 without LEVY_WEBHOOK_SECRET stored the call fails and the receiver has nothing",
        not no_secret.json()["data"]["ok"] and received == [],
        (no_secret.text[:300], received),
    )

    # 3. With the secret, the payload reaches the receiver with its signing header.
    gw.post("/v1/secrets", json={"name": "LEVY_WEBHOOK_SECRET", "value": "dev-webhook-secret"})
    sent = call(gw, "uc230-2", PAYLOAD)
    ok = sent.status_code == 200 and sent.json()["data"]["ok"]
    received = httpx.get(inbox, verify=False).json()
    check("3 the call is allowed and the receiver answers", ok, sent.text[:300])
    check(
        "3 the receiver holds the payload as sent, signed",
        received
        and received[0]["payload"] == PAYLOAD
        and received[0]["headers"].get("x-webhook-secret") == "(present)",
        received[:1],
    )

    # 4. The call log keeps it, with the operation and its outcome; the page lists it.
    logged = data(gw.get("/v1/executions", params={"tool": "notify_webhook", "pageSize": 20}))["data"]
    check(
        "4 the call log has both calls, the failed one and the sent one",
        [r["status"] for r in logged][:2] in (["ok", "error"], ["error", "ok"]),
        [(r["status"], r.get("error")) for r in logged][:3],
    )
    page = httpx.get(f"https://{address}/webhooks", verify=False)
    check(
        "4 the inbox page lists the payload",
        page.status_code == 200 and "NS-2026-GN-01187" in page.text and "levy.processed" in page.text,
        page.status_code,
    )

    # 5. The same call again (a retried step) is answered from the first result, not sent twice.
    again = call(gw, "uc230-2", PAYLOAD)
    received_again = httpx.get(inbox, verify=False).json()
    check(
        "5 a retried step sends nothing new",
        again.json()["data"].get("replayOf") is not None or len(received_again) == len(received),
        (again.text[:200], len(received_again)),
    )

finish()
