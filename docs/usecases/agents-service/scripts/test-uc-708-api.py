"""uc-708, api layer: docs/usecases/agents-service/an-expired-named-account-waits-for-sign-in.md.

When the sign-in of an account that a step, an agent or a chat names expires (Salesforce answers 401 and refuses the
refresh), the call is refused naming that account and saying it needs a new sign-in; a workflow run waits with that
reason; a chat turn gets the sign-in card; and no call is ever sent to the team's other account. Every call goes
through the real chat, engine, worker and gateway on the scripted model (lib/several_accounts.py)."""

from __future__ import annotations

import time
from typing import Any

from several_accounts import QUERY, SF, add_org, flow, retail_on, rig, save_and_publish
from usecase_harness import check, data, finish

FLOW = "uc708_eu"


def refused(r: Any) -> bool:
    """Whether the gateway refused the call for a new sign-in of EU org: the system's refusal, carried as the call's
    output, naming the account and the event its next sign-in reports."""
    error = ((data(r) or {}).get("output") or {}).get("error") or {} if r.status_code == 200 else {}
    details = error.get("details") or {}
    return (
        error.get("code") == "AUTH_FAILED"
        and details.get("connection") == "EU org"
        and bool(details.get("connectedEvent"))
    )


def say(r: Any, thread: str, text: str) -> str:
    assert r.api is not None
    turn = r.api.post(
        f"/chat/threads/{thread}/messages",
        json={"content": text},
        headers=r.priya | {"Accept": "text/event-stream"},
        timeout=120,
    )
    return f"{turn.status_code} {turn.text[-2500:]}"


def run_until_parked(r: Any, flow_id: str, seconds: float = 90) -> dict[str, Any]:
    """Starts the workflow and reads it until it waits or ends."""
    assert r.api is not None
    started = data(r.api.post("/v1/runs", json={"workflowId": flow_id, "mode": "live", "input": {}}, headers=r.priya))
    rid = str((started or {}).get("runId") or "")
    detail: dict[str, Any] = {}
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        detail = data(r.api.get(f"/v1/runs/{rid}", headers=r.priya)) or {}
        if detail.get("status") in ("waiting", "succeeded", "failed", "cancelled"):
            break
        time.sleep(0.5)
    steps = [
        (s.get("nodeId"), s.get("status"), str(s.get("output") or s.get("error"))[:300])
        for s in detail.get("steps") or []
    ]
    return {
        "id": rid,
        "status": detail.get("status"),
        "outcome": detail.get("outcome"),
        "waiting": detail.get("waiting"),
        "steps": steps,
    }


with rig("uc-708", with_agents=True) as r:
    assert r.api is not None
    retail_on(r)
    add_org(r, "EU org", r.sf["eu_login_url"], "kestrel.eu")
    retail = r.sf["api_base"].removeprefix("https://")
    _, published = save_and_publish(r, flow(FLOW, {SF: "EU org"}))
    agent = data(r.api.post("/v1/agents", json={"name": "EU desk", "role": "Finds cases"}, headers=r.priya)) or {}
    aid = str(agent.get("id") or "ag_missing")
    draft = r.api.patch(f"/v1/agents/{aid}", json={"toolIds": ["salesforce_query"], "accounts": {SF: "EU org"}},
                        headers=r.priya)  # fmt: skip
    r.api.post(
        f"/v1/agents/{aid}/publish-requests", json={"version": (data(draft) or {}).get("version")}, headers=r.priya
    )
    thread = str((data(r.api.post("/chat/threads", json={"agentId": aid, "kbIds": []}, headers=r.priya)) or {})["id"])

    # 1. EU org's sign-in expires: Salesforce answers 401 and refuses the refresh. A call naming it is refused, says
    # it needs a new sign-in, and nothing reaches Retail org.
    eu_host = r.sf["eu_base"].removeprefix("https://")
    r.sf["fake"].refuse_refresh = True
    r.sf["fake"].revoke_sessions(eu_host)
    since = r.calls_so_far()
    first = r.call(accounts={SF: "EU org"})
    again = r.call(accounts={SF: "EU org"})
    hosts = r.hosts(since)
    row = r.row(r.priya, r.ids["EU org"])
    check(
        "1 a call naming EU org after its sign-in expired is refused for a new sign-in of EU org, never sent to Retail org",
        refused(first) and refused(again) and retail not in hosts
        and row.get("state") in ("expired", "refused", "revoked") and "EU org" in again.text,
        {"first": first.text[:400], "again": again.text[:400], "hosts": hosts, "state": row.get("state")},
    )  # fmt: skip
    # 2. A published workflow whose step names EU org waits with that reason instead of running on Retail org.
    since = r.calls_so_far()
    run = run_until_parked(r, FLOW)
    check(
        "2 a run whose step names the expired EU org waits for its sign-in, and nothing reaches Retail org",
        (data(published) or {}).get("status") == "approved" and run["status"] == "waiting"
        and "EU org" in str(run["waiting"]) and retail not in r.hosts(since),
        run,
    )  # fmt: skip
    # 3. A chat whose agent names EU org gets the sign-in card for EU org, and nothing reaches Retail org.
    since = r.calls_so_far()
    said = say(r, thread, f'call salesforce_query {{"q": "{QUERY}"}}')
    check(
        "3 a chat turn on the expired EU org gets the sign-in card naming EU org, never Retail org's answer",
        '"AUTH_FAILED"' in said and '"connectedEvent"' in said and '"connection": "EU org"' in said
        and retail not in r.hosts(since),
        {"turn": said[-1500:], "hosts": r.hosts(since)},
    )  # fmt: skip
    # 4. Priya signs EU org in again: the waiting run goes on, in EU org.
    r.sf["fake"].refuse_refresh = False
    since = r.calls_so_far()
    r.sign_in(r.priya, r.ids["EU org"], "kestrel.eu")
    deadline, after = time.monotonic() + 90, {}
    while time.monotonic() < deadline:
        after = data(r.api.get(f"/v1/runs/{run['id']}", headers=r.priya)) or {}
        if after.get("status") in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(0.5)
    hosts = r.hosts(since)
    check(
        "4 once EU org is signed in again the waiting run goes on and its query runs in EU org",
        after.get("status") == "succeeded" and after.get("outcome") == "done" and eu_host in hosts and retail not in hosts,
        {"status": after.get("status"), "outcome": after.get("outcome"), "hosts": hosts},
    )  # fmt: skip

finish()
