"""A tool's access class (read or write) and the write approval policy that decides how many approvers a call needs.

tools-service's registry is the authority: with a gateway configured, the review service asks it over HTTP and never
reads tools-service's code or tables. Without one (tools run in this process) the same rule is applied locally: the
catalogue's access, and send_reply, a workflow tool outside the catalogue, is a write.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ops_service_kit.errors import ApiError

from .deps import Runtime

WORKFLOW_TOOLS = {"send_reply": "write"}


class ToolsUnavailable(ApiError):
    status = 503
    code = "tools_unavailable"


@dataclass(frozen=True)
class WritePolicy:
    """How a write to a tool is approved (docs/architecture/tool-lifecycle.md, "Write approval"): `approvers` distinct
    people, from `approver_team` when the registry names one, and whether the person who asked may be one."""

    access: str
    approvers: int
    approver_team: str | None
    self_approval: bool


async def policy_of(rt: Runtime, tool: str) -> WritePolicy:
    if rt.tools is not None:
        try:
            data = await rt.tools.tool_policy(tool)
        except httpx.HTTPError as e:
            raise ToolsUnavailable(
                f"The tools service cannot be reached, so the approvals {tool} needs are unknown. Try again shortly."
            ) from e
        access = str(data["access"])
        approval: dict[str, Any] = data.get("approval") or {}
        return WritePolicy(
            access=access,
            approvers=int(approval.get("approvers") or 1),
            approver_team=approval.get("approverTeam"),
            self_approval=bool(approval.get("selfApproval")),
        )
    access = await access_of(rt, tool)
    definition = rt.catalog.tool(tool)
    return WritePolicy(access, definition.approvers if definition else 1, None, False)


async def access_of(rt: Runtime, tool: str) -> str:
    if rt.tools is not None:
        try:
            return await rt.tools.tool_access(tool)
        except httpx.HTTPError as e:
            # No local fallback: tools-service is the authority on how many approvers a call needs.
            raise ToolsUnavailable(
                f"The tools service cannot be reached, so the approvals {tool} needs are unknown. Try again shortly."
            ) from e
    if tool in WORKFLOW_TOOLS:
        return WORKFLOW_TOOLS[tool]
    definition = rt.catalog.tool(tool)
    return definition.access if definition else "unknown"
