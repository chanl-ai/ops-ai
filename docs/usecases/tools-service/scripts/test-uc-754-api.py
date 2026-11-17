"""uc-754 approval fails closed, api layer: docs/usecases/tools-service/approval-fails-closed-when-the-approval.md.
tools-service starts with no platform client, so it cannot read the team's approval rules (`WriteApprovals.levels`,
services/tools-service/src/ops_tools/modules/policy.py). A write that needs approval must then be held or refused and
never run. Expected RED today: policy.py:56 answers empty levels instead of "cannot read", so the write runs unasked.
Mock upstream (lib/fake_bank_https.py) and the scripted model; no model call."""

from __future__ import annotations

import json
import time

from fake_bank_https import HOST, fake_bank
from main_chains import ACCOUNT, TEAM, agent_with, holds, publish_bank_module
from usecase_harness import AGENTS_PORT, TOOLS_PORT, agents, check, data, finish, sse, tools

RUN = int(time.time())
settings = {"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}


def write_turn(api, agent: str, write: str):  # type: ignore[no-untyped-def]
    thread = data(api.post("/chat/threads", json={"agentId": agent, "kbIds": []}, headers=TEAM))["id"]
    res = api.post(
        f"/chat/threads/{thread}/messages",
        json={"content": f"call {write} {json.dumps({'accountId': ACCOUNT})}"},
        headers={**TEAM, "Accept": "text/event-stream"},
    )
    events = sse(res.text)
    widget = next((e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval"), None)
    return events, widget


# tools() builds no platform client: no OPS_PLATFORM_URL reaches the run (usecase_harness._env drops it).
with (
    fake_bank() as bank,
    agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}") as api,
    tools(settings={**bank.settings, **settings}) as gw,
):
    gw.post("/v1/egress/hosts", json={"value": HOST, "note": "main chains mock upstream"})
    gw.post("/v1/egress/ranges", json={"value": bank.range, "note": "main chains mock upstream network"})
    _, _, gated = publish_bank_module(gw, RUN, approval=True)
    _, _, plain = publish_bank_module(gw, RUN + 1, approval=False)
    agent = agent_with(api, RUN, [gated, plain])

    # Non-vacuous: with the write's own approval switch on, the write waits, so the harness can see a hold when one is asked for.
    events, widget = write_turn(api, agent, gated)
    check("1 a write whose own switch asks for approval waits on a card", widget is not None, [e["type"] for e in events])
    check("2 nothing reached the upstream", not holds(bank), len(holds(bank)))

    # The failing case: the approval rules cannot be read, and the write has no switch of its own.
    events, widget = write_turn(api, agent, plain)
    ended = next((e["call"] for e in events if e["type"] == "tool_end"), {})
    check(
        "3 with the approval rules unreadable the write is held for approval or refused",
        widget is not None or ended.get("status") in ("refused", "error", "blocked"),
        {"widget": widget, "status": ended.get("status"), "output": ended.get("output")},
    )
    check("4 and it never ran: the upstream saw no hold", not holds(bank), len(holds(bank)))
finish()
