"""The service events a tool module's reviews are reported with (on the outbox): each starts the system
workflow that waits for a person in Human Tasks and then applies the decision through the gateway. tools-service
never opens a review in agents-service itself.

The payload carries everything the reviewer's sheet draws, fixed when the request is made, so a module edited
afterwards does not change what was asked."""

from __future__ import annotations

from typing import Any

from ops_access.platform_events import POLICY_CHANGED

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


def policy_changed_event(m: dict[str, Any], o: dict[str, Any], team_id: str, actor: str | None) -> dict[str, Any]:
    """A tool's own approval answer changed, for the team that edited it. agents-service keeps each team's tool list
    for up to 30 s and the list carries every write's answer, so it drops the list when it hears this, as it does for
    a team's appChanges (platform-service sends that one). The key repeats for a retry of the same save only."""
    return {
        "tenant_id": m["tenant_id"],
        "team_id": team_id,
        "name": POLICY_CHANGED,
        "key": f"tool:{o['name']}:{m['id']}:{m['revision']}",
        "actor": actor,
        "payload": {"key": f"tool:{o['name']}"},
    }
