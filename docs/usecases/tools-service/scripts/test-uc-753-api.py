"""uc-753 an agent reads with a tool, asks for approval, and the write runs only after approval, api layer:
docs/usecases/tools-service/an-agent-reads-with-a-tool.md. MODE=mock (default): the scripted model, a tool module on a
mock upstream (lib/fake_bank_https.py), so "ran" and "nothing ran" are read from the upstream's side. MODE=real runs on a
real model and the Salesforce test org (lib/main_chains.py)."""

from __future__ import annotations

import json
import time

from fake_bank_https import HOST, fake_bank
from main_chains import ACCOUNT, MAYA, TEAM, agent_with, holds, publish_bank_module
from usecase_harness import AGENTS_PORT, TOOLS_PORT, agents, check, data, finish, service_headers, sse, tools

RUN = int(time.time())
settings = {"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}


def turn(api, thread: str, text: str) -> list[dict]:  # type: ignore[no-untyped-def]
    res = api.post(f"/chat/threads/{thread}/messages", json={"content": text}, headers={**TEAM, "Accept": "text/event-stream"})
    return sse(res.text)


with (
    fake_bank() as bank,
    agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}") as api,
    tools(settings={**bank.settings, **settings}) as gw,
):
    gw.post("/v1/egress/hosts", json={"value": HOST, "note": "main chains mock upstream"})
    gw.post("/v1/egress/ranges", json={"value": bank.range, "note": "main chains mock upstream network"})
    _, read, write = publish_bank_module(gw, RUN, approval=True)
    agent = agent_with(api, RUN, [read, write])
    thread = data(api.post("/chat/threads", json={"agentId": agent, "kbIds": []}, headers=TEAM))["id"]

    events = turn(api, thread, f"call {read} {json.dumps({'accountId': ACCOUNT})}")
    ended = next((e["call"] for e in events if e["type"] == "tool_end"), {})
    check(
        "1 the read runs at once with no approval card and answers from the upstream",
        ended.get("status") == "success" and "1200.5" in json.dumps(ended.get("output")) and not any(e["type"] == "widget" for e in events),
        ended,
    )

    events = turn(api, thread, f"call {write} {json.dumps({'accountId': ACCOUNT})}")
    widget = next((e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval"), None)
    check("2 the write stops on a pending approval card", widget is not None and widget["state"] == "pending", widget or [e["type"] for e in events])
    # Non-vacuous: the upstream saw no hold while the card was pending, so the later hold is the approval's doing.
    check("3 nothing reached the upstream while the write waited", not holds(bank), len(holds(bank)))
    url = f"/chat/threads/{thread}/messages/{events[0]['messageId']}/widgets/{(widget or {}).get('id')}/actions"
    step = data(api.post("/v1/auth/step-up", json={"password": "northfield-demo"}, headers={**TEAM, **MAYA}))["token"]
    approved = api.post(url, json={"type": "approve", "stepUpToken": step}, headers={**TEAM, **MAYA})
    check(
        "4 a second person approves and the write runs once",
        approved.status_code == 200 and data(approved)["state"] == "approved" and len(holds(bank)) == 1,
        (approved.status_code, approved.text[:200], len(holds(bank))),
    )
    seen = sorted(
        (name, r["decision"], r["status"])
        for name in (read, write)
        for r in data(gw.get("/v1/executions", params={"tool": name}))["data"]
    )
    check(
        "5 the call log holds one row per tool call, the write allowed on the approval",
        seen == sorted([(read, "allow", "ok"), (write, "allow", "ok")]),
        seen,
    )
finish()
