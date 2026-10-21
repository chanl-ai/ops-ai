"""uc-128 chat starts on the team's default agent, api layer: docs/usecases/agents-service/team-default-agent.md.

The agents service on the scripted model under dev auth, so the role checks are the unit suite's
(services/agents-service/tests/api/test_team_default_agent.py) and the ui layer's; here the flows run end to end."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from usecase_harness import agents, check, data, finish, sse

ROOT = Path(__file__).resolve().parents[4]
TEAM = {"X-Team-Id": "team_ops", "X-Dev-User": "m.okafor@harborpine.example"}


def say(api: Any, thread: str, text: str) -> list[dict[str, Any]]:
    res = api.post(
        f"/chat/threads/{thread}/messages",
        json={"content": text},
        headers={**TEAM, "Accept": "text/event-stream"},
        timeout=120,
    )
    if res.status_code != 200:
        raise SystemExit(f"FAIL send: {res.status_code} {res.text[:300]}")
    return sse(res.text)


with agents() as api:
    none = api.post("/chat/threads", json={"kbIds": []}, headers=TEAM)
    check(
        "1 no default yet: a chat without an agent is refused",
        none.status_code == 409 and none.json()["error"]["code"] == "no_default_agent",
        none.text[:200],
    )

    set_ = api.put("/v1/chat/default-agent", json={"agentId": "ag_branch"}, headers=TEAM)
    thread = data(api.post("/chat/threads", json={"kbIds": []}, headers=TEAM))
    check(
        "2 the chat starts on the team default",
        set_.status_code == 200 and thread["agentId"] == "ag_branch",
        {"set": set_.text[:200], "agent": thread["agentId"]},
    )

    events = say(api, thread["id"], 'call agent__ag_dispute {"question": "Can I dispute a card charge?"}')
    ended = [e["call"] for e in events if e.get("type") == "tool_end"]
    asked = [
        (c["name"], (c.get("output") or {}).get("status"), (c.get("output") or {}).get("agentName")) for c in ended
    ]
    check(
        "3 the default asks Card Dispute Resolver, which answers with its own turn",
        asked == [("agent__ag_dispute", "answered", "Card Dispute Resolver")],
        asked,
    )

    url = f"/chat/threads/{thread['id']}"
    moved = data(api.patch(url, json={"agentId": "ag_dispute"}, headers=TEAM))
    say(api, thread["id"], "Hello")
    back = data(api.patch(url, json={"agentId": "ag_branch"}, headers=TEAM))
    check(
        "4 the handover names the start agent, and Back clears it",
        (moved["agentId"], moved.get("startAgentId"), back["agentId"], back.get("startAgentId"))
        == ("ag_dispute", "ag_branch", "ag_branch", None),
        {"moved": [moved["agentId"], moved.get("startAgentId")], "back": [back["agentId"], back.get("startAgentId")]},
    )

    reloaded = data(api.get(url, headers=TEAM))["messages"]
    names = [m.get("agentName") for m in reloaded if m["role"] == "assistant"]
    check(
        "5 a reload credits each reply to the agent that wrote it",
        names == ["Branch Concierge", "Card Dispute Resolver"],
        names,
    )

src = ROOT / "services" / "agents-service" / "src" / "ops_agents"
hits = subprocess.run(
    [
        "grep",
        "-rnE",
        "ag_(branch|dispute|fraud)",
        str(src / "api" / "routers" / "chat.py"),
        str(src / "api" / "agent_calls.py"),
        str(src / "store" / "team_defaults.py"),
    ],
    capture_output=True,
    text=True,
    check=False,
).stdout
check("6 no agent id is named in the default path", hits == "", hits[:300])
finish()
