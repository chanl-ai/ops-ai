"""uc-753 an agent reads with a tool, asks for approval, and the write runs only after approval, api layer:
docs/usecases/tools-service/an-agent-reads-with-a-tool.md. MODE=mock (default): the scripted model, a tool module on a
mock upstream (lib/fake_bank_https.py), so "ran" and "nothing ran" are read from the upstream's side. MODE=real runs on a
real model and the Salesforce test org (lib/main_chains.py)."""

from __future__ import annotations

import json
import time

from main_chains import ACCOUNT, agent_with, bank_stack, holds, publish_bank_module
from usecase_harness import check, data, finish, sse

RUN = int(time.time())


with bank_stack() as stack:
    api, gw, bank, who = stack.api, stack.gw, stack.bank, stack.who
    james, maya = who["builder"], who["approver"]

    def turn(thread: str, text: str) -> list[dict]:  # type: ignore[type-arg]
        res = api.post(f"/chat/threads/{thread}/messages", json={"content": text}, headers={**james, "Accept": "text/event-stream"})
        return sse(res.text)

    _, read, write = publish_bank_module(gw, RUN, approval=True, team=james, security=who["security"])
    agent = agent_with(api, RUN, [read, write], james)
    thread = data(api.post("/chat/threads", json={"agentId": agent, "kbIds": []}, headers=james))["id"]

    events = turn(thread, f"call {read} {json.dumps({'accountId': ACCOUNT})}")
    ended = next((e["call"] for e in events if e["type"] == "tool_end"), {})
    check(
        "1 the read runs at once with no approval card and answers from the upstream",
        ended.get("status") == "success" and "1200.5" in json.dumps(ended.get("output")) and not any(e["type"] == "widget" for e in events),
        ended,
    )

    events = turn(thread, f"call {write} {json.dumps({'accountId': ACCOUNT})}")
    widget = next((e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval"), None)
    check("2 the write stops on a pending approval card", widget is not None and widget["state"] == "pending", widget or [e["type"] for e in events])
    # Non-vacuous: the upstream saw no hold while the card was pending, so the later hold is the approval's doing.
    check("3 nothing reached the upstream while the write waited", not holds(bank), len(holds(bank)))
    url = f"/chat/threads/{thread}/messages/{events[0]['messageId']}/widgets/{(widget or {}).get('id')}/actions"
    step = data(stack.accounts.post("/v1/auth/step-up", json={"password": "northfield-demo"}, headers=maya))["token"]
    approved = api.post(url, json={"type": "approve", "stepUpToken": step}, headers=maya)
    check(
        "4 a second person approves and the write runs once",
        approved.status_code == 200 and data(approved)["state"] == "approved" and len(holds(bank)) == 1,
        (approved.status_code, approved.text[:200], len(holds(bank))),
    )
    seen = sorted(
        (name, r["decision"], r["status"])
        for name in (read, write)
        for r in data(gw.get("/v1/executions", params={"tool": name}, headers=james))["data"]
    )
    check(
        "5 the call log holds one row per tool call, the write allowed on the approval",
        seen == sorted([(read, "allow", "ok"), (write, "allow", "ok")]),
        seen,
    )
finish()
