"""uc-704, api layer: docs/usecases/agents-service/the-model-is-told-the-account-in-use.md.

With two Salesforce accounts and EU org chosen for a chat, the model is told "Salesforce: on · uses EU org (<EU
host>)" on its apps line, a request in words for another org changes nothing (the call still runs in the EU org), and
no tool takes an account input. The chat runs on the team's default agent through the real chat, gateway and fake
Salesforce on the scripted model, which repeats its apps line when asked "Which apps can you reach?"
(services/agents-service/tests/conftest.py, lib/several_accounts.py)."""

from __future__ import annotations

import time
from typing import Any

from several_accounts import QUERY, SF, add_org, retail_on, rig
from steps import required
from usecase_harness import check, data, finish, sse, turn_text


def say(r: Any, thread: str, text: str) -> str:
    assert r.api is not None
    turn = r.api.post(
        f"/chat/threads/{thread}/messages",
        json={"content": text},
        headers=r.priya | {"Accept": "text/event-stream"},
        timeout=120,
    )
    return f"{turn.status_code} {turn.text}"


with rig("uc-704", with_agents=True) as r:
    assert r.api is not None
    sf = r.sf
    retail_on(r)
    add_org(r, "EU org", sf["eu_login_url"], "kestrel.eu")
    eu = sf["eu_base"].removeprefix("https://")
    agent = required(r.api.post("/v1/agents", json={"name": "Desk", "role": "Answers the team"}, headers=r.priya), "/v1/agents")
    aid = str(agent.get("id"))
    draft = required(r.api.patch(f"/v1/agents/{aid}", json={"toolIds": ["salesforce_query"]}, headers=r.priya), "grant the tool")
    r.api.post(f"/v1/agents/{aid}/publish-requests", json={"version": draft.get("version")}, headers=r.priya)
    # The apps line is written for the team's default agent only (api/apps_line.py).
    r.api.put("/v1/chat/default-agent", json={"agentId": aid}, headers=r.priya)
    thread = str((required(r.api.post("/chat/threads", json={"kbIds": []}, headers=r.priya), "/chat/threads")).get("id"))
    picked = r.api.put(
        f"/chat/threads/{thread}/connectors", json={"off": [], "accounts": {SF: "EU org"}}, headers=r.priya
    )

    # 1. The model is told the account in use and what it points at.
    told = say(r, thread, "Which apps can you reach?")
    said = turn_text(sse(told.split(" ", 1)[1]))
    line = next((x for x in said.splitlines() if x.startswith("Salesforce: on")), "")
    check(
        "1 the model's apps line reads Salesforce: on · uses EU org, with the EU org's host",
        picked.status_code == 200 and "uses EU org" in line and eu in line,
        {"picked": picked.text[:200], "line": line, "said": said[:600]},
    )

    # 2. Asking in words for the retail org changes nothing: the query still runs in the EU org.
    before = r.calls_so_far()
    asked = say(r, thread, f'Use the retail org. call salesforce_query {{"q": "{QUERY}"}}')
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not r.hosts(before):
        time.sleep(0.5)
    check(
        "2 after 'use the retail org' the query still runs in the EU org",
        r.hosts(before) == [eu],
        {"hosts": r.hosts(before), "turn": asked[-400:]},
    )

    # 3. No tool the agent holds takes an account input, so the model cannot switch accounts.
    tool = data(r.api.get("/v1/tools/salesforce_query", headers=r.priya)) or {}
    inputs = set(((tool.get("inputSchema") or {}).get("properties") or {}).keys())
    check(
        "3 salesforce_query takes no account input",
        bool(inputs) and not any("account" in k.lower() for k in inputs),
        {"inputs": sorted(inputs), "tool": str(tool)[:300]},
    )

finish()
