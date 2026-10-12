"""A tool's access class (read, write, money_movement), which decides how many approvers a call needs.

tools-service's registry is the authority: with a gateway configured, the review service asks it over HTTP and never
reads tools-service's code or tables. Without one (tools run in this process) the same rule is applied locally: the
catalogue's access, and send_reply, a workflow tool outside the catalogue, is a write.
"""

from __future__ import annotations

import httpx

from ops_service_kit.errors import ApiError

from .deps import Runtime

WORKFLOW_TOOLS = {"send_reply": "write"}


class ToolsUnavailable(ApiError):
    status = 503
    code = "tools_unavailable"


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
