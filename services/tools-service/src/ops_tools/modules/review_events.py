"""The service events a tool module's reviews are reported with (c-257, on c-258's outbox): each starts the system
workflow that waits for a person in Human Tasks and then applies the decision through the gateway. tools-service
never opens a review in agents-service itself.

The payload carries everything the reviewer's sheet draws, fixed when the request is made, so a module edited
afterwards does not change what was asked."""

from __future__ import annotations

from typing import Any

ACCESS_REQUESTED = "tool_access.requested"
# The platform tool the access request's system workflow applies its decision with, run in this gateway (tools.py).
APPLY_ACCESS = "apply_tool_access"
# Each system-only tool and the one system workflow that may call it: a team's own workflow, even one whose review a
# person approved, is refused, so no workflow but the platform's grants access or publishes a version.
SYSTEM_TOOLS: dict[str, str] = {APPLY_ACCESS: "tool_access_request"}


def access_event(m: dict[str, Any], a: dict[str, Any]) -> dict[str, Any]:
    """A workflow's request for the module's operations, for the team that decides it, started by the person asking."""
    expires = a.get("expires_at")
    return {
        "tenant_id": m["tenant_id"],
        "team_id": a["decider_team"],
        "name": ACCESS_REQUESTED,
        "key": a["id"],
        "actor": a.get("requested_by_email"),
        "payload": {
            "moduleId": m["id"],
            "moduleName": m["display_name"],
            "approvalId": a["id"],
            "workflowId": a["workflow_id"],
            "workflowName": a["workflow_name"],
            "operations": list(a["operations"]),
            "environment": a["environment"],
            "expiresAt": expires.isoformat() if expires is not None else None,
            "justification": a["justification"],
            "deciderTeam": a["decider_team"],
            "requestedBy": a["requested_by"],
            # The review step refuses this person as its decider (notDecidedBy), as the apply step does.
            "requestedByEmail": a.get("requested_by_email"),
        },
    }
