# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-610 an agent with many tools finds the one it needs by searching, api layer:
docs/usecases/agents-service/an-agent-finds-its-tool-by-search.md.

The banker demo's stack (harness demo(): models-service on the fake OpenAI with the committed demo rules, tools-service
and the core bank, kb-service) with the install flag tool_search on (OPS_FLAGS) and OPS_TOOL_SEARCH_ABOVE=3, so an agent
holding the bank's operations searches for its tools. ag_advisor is granted every bank operation but open_dispute and
published. The fake's uc610 rules call a tool only when it is offered, so which rule fires shows what each request
offered. No real model is called."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from usecase_harness import DEMO_MAYA, chat, check, data, demo, finish, turn_text

AGENT = "ag_advisor"
UNGRANTED = "open_dispute"
OPS = {"X-Team-Id": "team_ops"}
MAYA = {**OPS, "X-Dev-User": DEMO_MAYA}


def calls(events: list[dict[str, Any]], name: str | None = None) -> list[dict[str, Any]]:
    ended = [e["call"] for e in events if e.get("type") == "tool_end"]
    return [c for c in ended if name is None or c["name"] == name]


def grant_bank(api: httpx.Client) -> list[str]:
    """Every bank operation but open_dispute on the agent, published (dev approves its own request)."""
    tools = [t["id"] for t in data(api.get("/v1/tools", headers=OPS)) if not str(t["id"]).startswith("workflow:")]
    held = [t for t in tools if t != UNGRANTED]
    patched = data(api.patch(f"/v1/agents/{AGENT}", json={"toolIds": held}, headers=OPS))
    body = {"version": patched["version"], "note": "uc-610 many tools"}
    published = api.post(f"/v1/agents/{AGENT}/publish-requests", json=body, headers=OPS)
    assert published.status_code < 300, published.text[:300]
    return held


def main() -> None:
    # Read by the stack's agents-service, which demo() starts with this process's environment.
    os.environ |= {"OPS_FLAGS": json.dumps(["tool_search"]), "OPS_TOOL_SEARCH_ABOVE": "3"}
    with demo() as d:
        api = d.api
        held = grant_bank(api)
        check("the agent holds more tools than the threshold", len(held) > 3 and UNGRANTED not in held, held)

        _, balance = chat(api, AGENT, "uc610 balance of BUS-7781")
        names = [c["name"] for c in calls(balance)]
        account = calls(balance, "get_account")
        check(
            "1 only the built-ins are offered first: the agent searches before it can call get_account",
            names[:2] == ["search_tools", "get_account"],
            names,
        )
        check(
            "2 the search finds get_account, which then runs through the gateway and answers",
            bool(account)
            and account[0]["status"] == "success"
            and "48210" in json.dumps(account[0].get("output"))
            and "uc610" in turn_text(balance),
            {"account": account[:1], "text": turn_text(balance)[:200]},
        )

        _, notes = chat(api, AGENT, "uc610 notes for CUS-1002")
        listed = calls(notes, "list_customer_notes")
        check(
            "3 a different question finds a different tool",
            [c["name"] for c in calls(notes)][:2] == ["search_tools", "list_customer_notes"]
            and listed[0]["status"] == "success",
            [c["name"] for c in calls(notes)],
        )

        thread, hold = chat(api, AGENT, "uc610 hold on BUS-7781")
        widget = next((e["widget"] for e in hold if e["type"] == "widget" and e["widget"]["kind"] == "approval"), None)
        check("4 a found write pauses for approval", widget is not None, [e["type"] for e in hold])
        if widget is not None:
            url = f"/chat/threads/{thread}/messages/{hold[0]['messageId']}/widgets/{widget['id']}/actions"
            action: dict[str, Any] = {"type": "approve"}
            if widget.get("stepUp"):
                minted = data(api.post("/v1/auth/step-up", json={"password": "northfield-demo"}, headers=MAYA))
                action["stepUpToken"] = minted["token"]
            approved = api.post(url, json=action, headers=MAYA)
            thread_now = data(api.get(f"/chat/threads/{thread}", headers=MAYA)) or {}
            last: dict[str, Any] = (thread_now.get("messages") or [{}])[-1]
            ran = [c for c in last.get("toolCalls") or [] if c.get("name") == "place_hold"]
            check(
                "5 after approval the resumed turn runs the hold once and answers",
                approved.status_code == 200
                and len(ran) == 1
                and ran[0].get("status") == "success"
                and "hold is in place" in str(last.get("content")),
                {"approved": approved.text[:200], "ran": ran, "text": last.get("content", "")[:200]},
            )

        _, dispute = chat(api, AGENT, "uc610 dispute on TX-1")
        searched = calls(dispute, "search_tools")
        check(
            "6 a search never finds a tool the agent is not granted",
            bool(searched) and UNGRANTED not in json.dumps(searched[0].get("output")) and not calls(dispute, UNGRANTED),
            searched[:1],
        )
        _, forced = chat(api, AGENT, "uc610 force dispute on TX-1")
        tried = calls(forced, UNGRANTED)
        check(
            "7 calling it by name anyway is refused clearly, nothing is sent, and the reply finishes",
            bool(tried)
            and all(c["status"] != "success" for c in tried)
            and not [e for e in forced if e.get("type") == "error"]
            and any(e.get("type") == "done" for e in forced),
            {"tried": tried, "events": [e for e in forced if e.get("type") in ("error", "tool_end")][-3:]},
        )
    finish()


if __name__ == "__main__":
    main()
