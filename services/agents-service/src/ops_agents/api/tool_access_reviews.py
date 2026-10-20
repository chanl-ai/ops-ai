"""A workflow's request for a tool module's operations as it was reviewed before it ran as a system workflow (c-166,
superseded by c-257's tool_access_request): only decided ones remain readable here. A request still pending is
listed and decided as its run; `publish_reviews` lists none and refuses a decision on one."""

from __future__ import annotations

from typing import Any

from .agent_registry import review_view
from .deps import Runtime
from .review_sla import sla_hours

KIND = "tool_access"
ENVIRONMENTS = {"production": "Production", "test": "Test"}


def team(req: dict[str, Any]) -> str | None:
    """The team whose reviewers decide it: the module's team, or the one an operation names as its approver."""
    return str(req["body"].get("deciderTeam") or "") or None


async def view(rt: Runtime, req: dict[str, Any]) -> dict[str, Any]:
    # A decision whose apply never reached tools-service left the request open there; the cut-over asks it again as
    # its run (review_copy), so nothing here retries it.
    body = req["body"]
    v = review_view(req, name=body["workflowName"], slug="", sla_hours=await sla_hours(rt))
    v.pop("publish", None)
    policy = {**v["policy"], "id": "gp_tool_access", "name": "Tool access", "reviewers": body["deciderTeam"]}
    environment = ENVIRONMENTS.get(str(body["environment"]), str(body["environment"]))
    return {
        **v,
        "title": f"Let {body['workflowName']} use {body['moduleName']}?",
        "workflowId": body["workflowId"],
        "actionTool": "grant_tool_access",
        "policy": policy,
        "proposal": f"{environment}: {', '.join(body['operations'])} until {str(body['expiresAt'])[:10]}",
        "reasoning": [str(body["justification"])] if body.get("justification") else [],
    }
