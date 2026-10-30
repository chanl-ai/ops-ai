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
        as_tools = service_headers("agents", service="tools", scopes=["workflows:view"])
        listed = api.get("/v1/workflow-refs", headers=as_tools)
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
        # Decided by its system workflow run in Human Tasks, as uc-010 shows; the decision itself is uc-053's.
        review_id = approval.get("reviewId", "")
        expected = f"tool_access.requested:{approval.get('id')}"
        check("the request names its workflow run", review_id == expected, review_id)
        on_module = gw.post(f"{MODULE}/approvals/{approval.get('id')}/decide", json={"decision": "approved"})
        check("the module page decides nothing (409)", on_module.status_code == 409, on_module.text[:200])
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
        # The grant is for the workflow's own team id even when the directory does not hold that team (c-423); it is
        # never handed to every team. A workflow no team owns is still refused.
        owner = {w["id"]: w for w in data(api.get("/v1/workflow-refs", headers=as_tools)) or []}.get(orphan_id, {})
        check(
            "a workflow of a team tools-service has no record of is granted for that team alone",
            unknown.status_code == 201 and owner.get("teamId") == "team_nobody",
            [unknown.status_code, owner],
        )
    time.sleep(31)  # agents-service is stopped; past the cache, the next lookup must reach it
    down = gw.post(f"{MODULE}/approvals", json=request("dispute_email"))
    check(
        "with agents-service stopped, a request is 503 workflows_unavailable, never a guess",
        down.status_code == 503 and down.json().get("error", {}).get("code") == "workflows_unavailable",
        down.text[:200],
    )

finish()
