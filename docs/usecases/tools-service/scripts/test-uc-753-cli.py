"""uc-753, cli layer: docs/usecases/tools-service/an-agent-reads-with-a-tool.md. A developer runs `opsai chat say` as the
builder: the read answers, the write stops on an approval. The approver runs `opsai tasks approve` with the password on
standard input; the write runs once and `opsai tools calls` lists both calls. Platform sign-in (lib/main_chains.py
bank_stack), the scripted model."""

from __future__ import annotations

import json
import time

from apps_walk import ops_cli
from main_chains import ACCOUNT, agent_with, bank_stack, holds, publish_bank_module
from usecase_harness import check, finish

RUN = int(time.time())

with bank_stack() as s:
    _, read, write = publish_bank_module(s.gw, RUN, approval=True, team=s.who["builder"], security=s.who["security"])
    agent = agent_with(s.api, RUN, [read, write], s.who["builder"])
    args = json.dumps({"accountId": ACCOUNT})

    code, said = ops_cli("builder", "chat", "say", "--agent", agent, "-m", f"call {read} {args}")
    turn = (said.get("turns") or [{}])[0] if isinstance(said, dict) else {}
    thread = said.get("thread") if isinstance(said, dict) else None
    tool = (turn.get("tools") or [{}])[0]
    check("1 the read runs at once with no approval card", code == 0 and tool.get("status") == "success" and "1200.5" in json.dumps(tool.get("output")) and not turn.get("widgets"), said if code else tool)

    code, said = ops_cli("builder", "chat", "say", "--thread", str(thread), "-m", f"call {write} {args}")
    turn = (said.get("turns") or [{}])[0] if isinstance(said, dict) else {}
    # Non-vacuous: the upstream saw no hold while the task waited, so the later hold is the approval's doing.
    check("2 the write stops on a pending approval and nothing reached the upstream", code == 0 and bool(turn.get("widgets")) and not holds(s.bank), (code, turn.get("widgets"), len(holds(s.bank))))

    code, tasks = ops_cli("approver", "tasks", "list", "--view", "open")
    rows = [t for t in (tasks if isinstance(tasks, list) else []) if write in json.dumps(t)]
    check("3 the approver's queue lists the write as a task", code == 0 and len(rows) == 1, tasks if not rows else rows)
    if rows:
        code, done = ops_cli("approver", "tasks", "approve", str(rows[0]["id"]), "--password-stdin", stdin="northfield-demo\n")
        check("4 the approver approves with the password on stdin and the write runs once", code == 0 and len(holds(s.bank)) == 1, (code, str(done)[:200], len(holds(s.bank))))
    else:
        check("4 the approver approves with the password on stdin and the write runs once", False, "no task to approve")

    code, calls = ops_cli("builder", "tools", "calls", "--limit", "50")
    seen = sorted((r.get("target"), r.get("decision"), r.get("status")) for r in (calls if isinstance(calls, list) else []) if r.get("target") in (read, write))
    check("5 the call log lists one allowed row per tool call", seen == sorted([(read, "allow", "ok"), (write, "allow", "ok")]), calls if not seen else seen)
finish()
