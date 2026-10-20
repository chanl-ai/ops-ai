"""uc-041 workflow approvals use agents-service's workflows, api layer:
docs/usecases/tools-service/workflow-approvals-use-agents-service-workflows.md. tools-service reads the workflows
from agents-service with its service token; both run on the scripted model, on the run's own database and ports."""

from __future__ import annotations

import time
from typing import Any

from usecase_harness import AGENTS_PORT, agents, check, data, finish, service_headers, tools

THREAD = f"uc041_{int(time.time())}"
MODULE = "/v1/tool-modules/mod_core_banking"


def request(workflow: str) -> dict[str, Any]:
    return {
        "workflowId": workflow,
        "environment": "production",
        "operations": ["get_customer_profile"],
        "expiresInDays": 90,
        "justification": "Disputes need the customer's profile",
    }


with tools(settings={"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}) as gw:
    with agents() as api:
        listed = api.get("/v1/internal/workflows", headers=service_headers("agents", service="tools"))
        rows = {w["id"]: w for w in data(listed)} if listed.status_code == 200 else {}
        check(
            "agents-service lists its workflows to a service token, the seeded ones owned by team_ops",
            rows.get("dispute_email", {}).get("teamId") == "team_ops",
            listed.text[:200],
        )
        made = gw.post(f"{MODULE}/approvals", json=request("dispute_email"))
        approval = data(made) if made.status_code == 201 else {}
        check(
            "an approval is requested for agents-service's dispute_email (201)",
            made.status_code == 201 and approval.get("workflowName") == rows.get("dispute_email", {}).get("name"),
            made.text[:200],
        )
        decide = f"{MODULE}/approvals/{approval.get('id')}/decide"
        own = gw.post(decide, json={"decision": "approved"})
        check("the requester cannot decide it (403)", own.status_code == 403, own.text[:200])
        other = gw.post(decide, json={"decision": "approved"}, headers={"X-Dev-User": "Maya Okafor"})
        check(
            "someone else in the module's owner team approves it",
            other.status_code == 200 and data(other).get("status") == "approved",
            other.text[:200],
        )
        call = gw.post(
            "/v1/calls",
            json={
                "tool": "get_customer_profile",
                "input": {"customerId": "CUS-118842"},
                "key": "w1",
                "runContext": {"thread": THREAD, "step": "w1", "act": "workflow:dispute_email"},
            },
            headers=service_headers("tools"),
        )
        logged = data(gw.get("/v1/executions", params={"thread": THREAD})).get("data", [])
        check(
            "a call as that workflow runs and is logged with its name",
            call.status_code == 200 and bool(logged) and logged[0].get("workflowId") == "dispute_email",
            [call.status_code, logged[:1]],
        )
        fixture = gw.post(f"{MODULE}/approvals", json=request("wf_wire"))
        check(
            "a workflow agents-service does not have is refused (400)", fixture.status_code == 400, fixture.text[:200]
        )
        orphan = api.post(
            "/v1/workflows", json={"name": "Orphan flow", "trigger": "manual"}, headers={"X-Team-Id": "team_nobody"}
        )
        orphan_id = data(orphan).get("id") if orphan.status_code == 201 else ""
        time.sleep(31)  # past the workflow list's 30 s cache, so tools-service sees the new workflow
        unknown = gw.post(f"{MODULE}/approvals", json=request(orphan_id))
        check(
            "a workflow whose team tools-service has no record of fails closed (422 naming the team)",
            unknown.status_code == 422 and "team_nobody" in unknown.text,
            unknown.text[:200],
        )
    time.sleep(31)  # agents-service is stopped; past the cache, the next lookup must reach it
    down = gw.post(f"{MODULE}/approvals", json=request("dispute_email"))
    check(
        "with agents-service stopped, a request is 503 workflows_unavailable, never a guess",
        down.status_code == 503 and down.json().get("error", {}).get("code") == "workflows_unavailable",
        down.text[:200],
    )

finish()
