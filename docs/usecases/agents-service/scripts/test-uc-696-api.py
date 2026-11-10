"""uc-696, api layer: docs/usecases/agents-service/an-agent-runs-in-the-account-it-names.md.

An agent that names an account answers a chat in that account, and a workflow it starts whose tool step names another
account runs that step in the step's account: the step's choice wins over the agent's. Every call goes through the real
chat, engine, worker and gateway on the scripted model (lib/several_accounts.py), and each call's log row names the
account it signed in with."""

from __future__ import annotations

import re
import time
from typing import Any

from several_accounts import QUERY, SF, add_org, flow, retail_on, rig, save_and_publish
from usecase_harness import check, data, finish

FLOW = "uc696_retail"


def newest_query_rows(r: Any, since: set[str]) -> list[dict[str, Any]]:
    """The gateway's call rows for salesforce_query not in `since`, newest first."""
    page = data(r.gw.get("/v1/executions", params={"pageSize": 50}, headers=r.priya)) or {}
    rows = page.get("data") if isinstance(page, dict) else page
    return [c for c in rows or [] if "salesforce_query" in str(c.get("target")) and c.get("id") not in since]


def seen(r: Any) -> set[str]:
    return {str(c.get("id")) for c in newest_query_rows(r, set())}


def wait_hosts(r: Any, before: int, want: int = 1, seconds: float = 60) -> list[str]:
    """The org hosts the fake answered since `before`, once `want` queries landed or the time ran out."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and len(r.hosts(before)) < want:
        time.sleep(0.5)
    return r.hosts(before)


def say(r: Any, thread: str, text: str) -> str:
    assert r.api is not None
    turn = r.api.post(
        f"/chat/threads/{thread}/messages",
        json={"content": text},
        headers=r.priya | {"Accept": "text/event-stream"},
        timeout=120,
    )
    return f"{turn.status_code} {turn.text[-1500:]}"


with rig("uc-696", with_agents=True) as r:
    assert r.api is not None
    sf = r.sf
    retail_on(r)
    add_org(r, "EU org", sf["eu_login_url"], "kestrel.eu")
    eu, retail = sf["eu_base"].removeprefix("https://"), sf["api_base"].removeprefix("https://")
    # The workflow the agent may start: one salesforce_query step naming Retail org.
    _, flow_live = save_and_publish(r, flow(FLOW, {SF: "Retail org"}))
    agent = data(r.api.post("/v1/agents", json={"name": "Case desk", "role": "Finds cases"}, headers=r.priya)) or {}
    aid = str(agent.get("id"))
    draft = r.api.patch(
        f"/v1/agents/{aid}",
        json={"toolIds": ["salesforce_query", f"workflow:{FLOW}"], "accounts": {SF: "EU org"}},
        headers=r.priya,
    )
    published = r.api.post(
        f"/v1/agents/{aid}/publish-requests", json={"version": (data(draft) or {}).get("version")}, headers=r.priya
    )
    thread = str((data(r.api.post("/chat/threads", json={"agentId": aid, "kbIds": []}, headers=r.priya)) or {})["id"])

    # 1. The agent's chat query runs in the agent's account, EU org, and its log row names that account.
    before, rows_before = r.calls_so_far(), seen(r)
    answered = say(r, thread, f'call salesforce_query {{"q": "{QUERY}"}}')
    hosts = wait_hosts(r, before)
    rows = newest_query_rows(r, rows_before)
    check(
        "1 the agent naming EU org answers a chat query in the EU org, and the call row names the EU account",
        (data(flow_live) or {}).get("status") == "approved" and (data(published) or {}).get("status") == "approved"
        and hosts == [eu] and [c.get("connectionId") for c in rows] == [r.ids["EU org"]],
        {"draft": draft.text[:200], "published": published.text[:200], "hosts": hosts, "turn": answered,
         "rows": [(c.get("connectionId"), c.get("status")) for c in rows], "eu": r.ids["EU org"]},
    )  # fmt: skip

    # 2. A workflow the agent starts, whose step names Retail org, runs that step in Retail org: the step wins.
    before, rows_before = r.calls_so_far(), seen(r)
    started = say(r, thread, f"call workflow__{FLOW} {{}}")
    hosts = wait_hosts(r, before)
    rows = newest_query_rows(r, rows_before)
    check(
        "2 the agent's workflow step naming Retail org runs in the production org, and its row names Retail org",
        hosts == [retail] and [c.get("connectionId") for c in rows] == [r.ids["retail"]],
        {"hosts": hosts, "turn": started, "rows": [(c.get("connectionId"), c.get("runId")) for c in rows],
         "steps": [str(st.get("error"))[:200] for rid in re.findall(r"wfrun_[0-9a-f]+", started)[:1]
                   for st in (data(r.api.get(f"/v1/runs/{rid}", headers=r.priya)) or {}).get("steps") or []
                   if st.get("status") == "error"],
         "retail": r.ids["retail"]},
    )  # fmt: skip

finish()
