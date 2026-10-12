"""uc-006 SLA timer breach escalates, api layer: docs/usecases/agents-service/sla-breach-escalates.md."""

from __future__ import annotations

import time

from usecase_harness import EMAILS, TEAM, agents, check, data, finish, run, state

from ops_identity import dev_service_signer, mint_service_token  # noqa: E402

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

with agents() as api:
    pub = api.post(f"/v1/graphs/{NAME}/versions", json={"definition": WORKFLOW}, headers=TEAM)
    check("workflow with an SLA'd human step published (201)", pub.status_code == 201, pub.text[:200])
    tid = str(data(api.post("/v1/threads", json={"graph": NAME, "metadata": {}}, headers=TEAM))["threadId"])
    code, events = run(api, tid, {"input": {"email": EMAILS[0]}})
    check("run paused on the human step", code == 200 and events[-1]["data"]["status"] == "interrupted", events[-1:])
    timers = {t["timerId"]: t["state"] for t in state(api, tid)["sla"]["timers"]}
    breach = next((t for t in timers if ":breach:" in t), "")
    check("a breach timer is open", timers.get(breach) == "open", timers)
    url = f"/v1/threads/{tid}/timers/{breach}/fire"

    no_token = api.post(url)
    check(
        "fire route refuses a caller without a service token (401)", no_token.status_code == 401, no_token.status_code
    )
    # Non-vacuous: firing before the timer is due must change nothing, so the escalation below is the timer's doing.
    api.post(url, headers=SERVICE)
    early = state(api, tid)["interrupt"]["payload"]["sla"]
    check(
        "an early fire leaves the review with tier1",
        early.get("group") == "tier1" and not early.get("escalated"),
        early,
    )

    time.sleep(1.3)
    fired = api.post(url, headers=SERVICE)
    check("fire after the deadline accepted", fired.status_code in (200, 202), fired.text[:200])
    s = state(api, tid)
    sla = s["interrupt"]["payload"]["sla"]
    check("review escalated to supervisors", sla.get("group") == "supervisors" and sla.get("escalated") is True, sla)
    events = [e["event"] for e in s["sla"]["events"]]
    check("breach and escalation recorded", events[-2:] == ["sla.breach", "sla.escalated"], events)

finish()
