"""uc-266 a workflow's write is checked against the team's sending policy before it goes out, api layer.

Doc: docs/usecases/tools-service/check-before-sending.md. platform-service (the checkBeforeSend setting),
models-service on the fake OpenAI (the judge's answers in agents-service tests/fixtures/ai-steps-fake-openai),
tools-service on its own model key (tools:check), agents-service and a worker. A workflow opens a case through the
gateway; open_case is a write that runs without approval, so only the check stands between it and the case.
"""

from __future__ import annotations

import time
from contextlib import ExitStack
from typing import Any

import httpx
from usecase_harness import (
    AGENTS_DIR,
    AGENTS_PORT,
    TOOLS_PORT,
    agents,
    bearer,
    check,
    data,
    engine_worker,
    fake_openai,
    finish,
    models,
    platform,
    signed_in,
    tools,
)

OPS = {"X-Team-Id": "team_ops"}
RULES = AGENTS_DIR / "tests" / "fixtures" / "ai-steps-fake-openai"
POLICY = "Never promise a refund, or any money back, in a case or a reply."
FLOW = {
    "schemaVersion": 2,
    "id": "uc266_open_case",
    "name": "Open a case",
    "nodes": [
        {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
        {
            "id": "open",
            "type": "ops.action.tool",
            "typeVersion": 1,
            "parameters": {"operation": "open_case", "input": {"subject": "$.input.subject"}},
        },
        {"id": "opened", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "opened"}},
        {"id": "held", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "held"}},
        {"id": "failed", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "failed"}},
    ],
    "connections": [
        {"from": {"node": "start", "port": "payload"}, "to": {"node": "open", "port": "in"}},
        {"from": {"node": "open", "port": "ok"}, "to": {"node": "opened", "port": "in"}},
        {"from": {"node": "open", "port": "refused"}, "to": {"node": "held", "port": "in"}},
        {"from": {"node": "open", "port": "error"}, "to": {"node": "failed", "port": "in"}},
    ],
}


def run(api: httpx.Client, subject: str) -> dict[str, Any]:
    started = data(
        api.post(
            "/v1/runs", json={"workflowId": FLOW["id"], "mode": "live", "input": {"subject": subject}}, headers=OPS
        )
    )
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        detail = data(api.get(f"/v1/runs/{started['runId']}", headers=OPS))
        if detail["status"] in ("succeeded", "failed", "cancelled"):
            step = next((s for s in detail["steps"] if s.get("nodeId") == "open"), {})
            return {"outcome": detail.get("outcome"), "output": step.get("output")}
        time.sleep(0.5)
    return {"outcome": "timed out"}


with ExitStack() as stack:
    people, _inner = stack.enter_context(platform())
    platform_url = str(people.base_url).rstrip("/")
    fake = stack.enter_context(fake_openai(RULES))
    models_url = stack.enter_context(models({"OPS_MODELS_FAKE_OPENAI_URL": fake}))
    stack.enter_context(
        tools(
            {
                "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}",
                "OPS_PLATFORM_URL": platform_url,
                "OPS_MODELS_URL": models_url,
                "OPS_MODELS_KEY": "mk_dev_tools_check",
            }
        )
    )
    gateway = f"http://127.0.0.1:{TOOLS_PORT}"
    api = stack.enter_context(agents(gateway_url=gateway, env={"OPS_PLATFORM_URL": platform_url}))
    stack.enter_context(engine_worker("uc266", {"OPS_GATEWAY_URL": gateway, "OPS_PLATFORM_URL": platform_url}))
    saved = api.post("/v1/workflows/definitions", json={"definition": FLOW}, headers=OPS)
    live = api.post(f"/v1/workflows/definitions/{FLOW['id']}/publish-requests", json={}, headers=OPS)
    check(
        "0 the workflow saves and goes live",
        saved.status_code == 201 and data(live)["status"] == "approved",
        saved.text[:200],
    )

    priya = bearer(signed_in(people, "p.shah@northfieldbank.com"), "team_ops")
    gw = httpx.Client(base_url=gateway, timeout=30)
    policy = gw.put(
        "/v1/send-policy", json={"text": POLICY}, headers={**OPS, "X-Dev-User": "p.shah@northfieldbank.com"}
    )
    check(
        "1 the team's sending policy is saved (v1)",
        policy.status_code == 200 and data(policy)["version"] == 1,
        policy.text[:200],
    )

    off = run(api, "Refund promised for the double charge")
    check("2 with check before sending off, the case opens", off["outcome"] == "opened", off)

    on = people.put("/v1/policies/checkBeforeSend", json={"value": True}, headers=priya)
    check("3 Priya turns check before sending on for team_ops", on.status_code == 200, on.text[:200])
    held = run(api, "Refund promised for the double charge again")
    check(
        "4 a case that promises a refund is held for a person with the reason",
        held["outcome"] == "held" and "promises a refund" in str(held.get("output")),
        held,
    )
    fine = run(api, "Card stopped working abroad")
    check("5 a case the policy allows opens at once", fine["outcome"] == "opened", fine)

finish()
