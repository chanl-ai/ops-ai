"""uc-753, sdk layer: docs/usecases/tools-service/an-agent-reads-with-a-tool.md. A builder signed in through the Python
SDK chats with an agent that holds a read and a write on the mock upstream; the read answers, the write waits as a Human
Task, an approver approves it through the SDK with a step-up, and the usage log holds both calls. Platform sign-in
(lib/main_chains.py bank_stack), the scripted model."""

from __future__ import annotations

import json
import time

from apps_walk import signed_sdk
from main_chains import ACCOUNT, agent_with, bank_stack, holds, publish_bank_module
from usecase_harness import check, finish

RUN = int(time.time())

with bank_stack() as s:
    _, read, write = publish_bank_module(s.gw, RUN, approval=True, team=s.who["builder"], security=s.who["security"])
    agent = agent_with(s.api, RUN, [read, write], s.who["builder"])
    james, maya = signed_sdk("builder"), signed_sdk("approver")
    thread = james.chat.start(agent, kb_ids=[])

    def say(text: str) -> list[dict]:
        return list(james.chat.say(thread["id"], text))

    events = say(f"call {read} {json.dumps({'accountId': ACCOUNT})}")
    ended = next((e["call"] for e in events if e.get("type") == "tool_end"), {})
    check(
        "1 the read runs at once with no approval card",
        ended.get("status") == "success" and "1200.5" in json.dumps(ended.get("output")) and not any(e.get("type") == "widget" for e in events),
        ended,
    )
    events = say(f"call {write} {json.dumps({'accountId': ACCOUNT})}")
    widget = next((e["widget"] for e in events if e.get("type") == "widget" and e["widget"]["kind"] == "approval"), None)
    # Non-vacuous: the upstream saw no hold while the task waited, so the later hold is the approval's doing.
    check("2 the write stops on a pending approval and nothing reached the upstream", widget is not None and widget["state"] == "pending" and not holds(s.bank), (widget, len(holds(s.bank))))
    waiting = [t for t in maya.tasks.list(view="open") if write in json.dumps(t)]
    check("3 the approver's queue holds the write as a Human Task", len(waiting) == 1, [t.get("title") for t in waiting])
    done = maya.tasks.approve(waiting[0]["id"], password="northfield-demo") if waiting else None
    check("4 the approver approves through the SDK and the write runs once", done is not None and len(holds(s.bank)) == 1, (str(done)[:200], len(holds(s.bank))))
    logged = sorted((name, r["decision"], r["status"]) for name in (read, write) for r in james.usage.list(tool=name))
    check("5 the usage log holds one allowed row per tool call", logged == sorted([(read, "allow", "ok"), (write, "allow", "ok")]), logged)
finish()
