"""uc-006 SLA timer breach escalates, api layer: docs/usecases/agents-service/sla-breach-escalates.md."""

from __future__ import annotations

import time
from typing import Any

from usecase_harness import EMAILS, TEAM, agents, check, data, finish, run, state

from ops_identity import dev_service_signer, mint_service_token

# The scheduler's Ed25519 service token for audience "agents", naming the tenant it fires for (dev key, dev only).
SERVICE = {
    "Authorization": "Bearer "
    + mint_service_token(dev_service_signer(), service="scheduler", audience="agents", tenant_id="local", ttl_s=600)
}
# A fixed name: publishing the same definition again returns its stored version, so runs do not pile up workflows.
NAME = "uc006_sla"
WORKFLOW = {
    "entry": "human",
    "nodes": [
        {
            "id": "human",
            "kind": "human",
            "config": {"group": "tier1", "sla": "1s", "onTimeout": "escalate", "escalateTo": "supervisors"},
        },
        {"id": "decide", "kind": "condition", "config": {"rule": "decision", "approved": "done", "rejected": "close"}},
        {"id": "done", "kind": "end", "config": {"status": "replied"}},
        {"id": "close", "kind": "end", "config": {"status": "closed"}},
    ],
    "edges": [{"source": "human", "target": "decide"}],
}

with agents(timer_poll_seconds=0.3) as api:
    pub = api.post(f"/v1/graphs/{NAME}/versions", json={"definition": WORKFLOW}, headers=TEAM)
    check("workflow with an SLA'd human step published (201)", pub.status_code == 201, pub.text[:200])
    tid = str(data(api.post("/v1/threads", json={"graph": NAME, "metadata": {}}, headers=TEAM))["threadId"])
    code, events = run(api, tid, {"input": {"email": EMAILS[0]}})
    check("run paused on the human step", code == 200 and events[-1]["data"]["status"] == "interrupted", events[-1:])
    timers = {t["timerId"]: t["state"] for t in state(api, tid)["sla"]["timers"]}
    breach = next((t for t in timers if ":breach:" in t), "")
    check("a breach timer is open", timers.get(breach) == "open", timers)
    # No HTTP route fires a timer (c-168): the agents service's PostgreSQL poller fires it once it is due.
    gone = api.post(f"/v1/threads/{tid}/timers/{breach}/fire", headers=SERVICE)
    check("no route fires a timer", gone.status_code in (404, 405), gone.status_code)
    # Non-vacuous: before the deadline the review stays with tier1, so the escalation below is the timer's doing.
    early = state(api, tid)["interrupt"]["payload"]["sla"]
    check(
        "before the deadline the review stays with tier1",
        early.get("group") == "tier1" and not early.get("escalated"),
        early,
    )

    sla: dict[str, Any] = {}
    s: dict[str, Any] = {}
    for _ in range(40):
        time.sleep(0.5)
        s = state(api, tid)
        sla = s["interrupt"]["payload"]["sla"]
        if sla.get("escalated"):
            break
    check("review escalated to supervisors", sla.get("group") == "supervisors" and sla.get("escalated") is True, sla)
    events = [e["event"] for e in s["sla"]["events"]]
    check("breach and escalation recorded", events[-2:] == ["sla.breach", "sla.escalated"], events)

finish()
