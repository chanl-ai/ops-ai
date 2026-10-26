"""A tool's access class (read or write) and the write approval policy that decides how many approvers a call needs.

tools-service's registry is the authority: with a gateway configured, the review service asks it over HTTP and never
reads tools-service's code or tables. Without one (tools run in this process) the same rule is applied locally: the
catalogue's access, and send_reply, a workflow tool outside the catalogue, is a write.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from ops_identity import ServiceCallError, ServiceUnreachable
from ops_service_kit.errors import ApiError

from .deps import Runtime

WORKFLOW_TOOLS = {"send_reply": "write", "send_acknowledgement": "write"}


class ToolsUnavailable(ApiError):
    status = 503
    code = "tools_unavailable"


@dataclass(frozen=True)
class WritePolicy:
    """How a write to a tool is approved (docs/architecture/tool-lifecycle.md, "Write approval"): `approvers` distinct
    people of the run's team (c-509; an approving team tools-service still names is ignored). Whether the person who
    asked may be one is the tenant's requesterMayDecide policy (c-186), not the tool's."""

    access: str
    approvers: int
    # Approving asks the approver for a step-up: the operation says so, or two people approve it.
    step_up: bool = False


# Each tool's policy as read once within `one_read_per_tool`; None outside it, where every call asks.
_READ: ContextVar[dict[str, WritePolicy] | None] = ContextVar("tool_policies_read", default=None)


@contextmanager
def one_read_per_tool() -> Generator[None]:
    """Within the block, tools-service is asked once per tool: a list of Human Tasks names a few tools many times, and
    asking per review made the list one call per waiting write. Held for one request only, so a policy changed in
    tools-service applies from the next request."""
    token = _READ.set({})
    try:
        yield
    finally:
        _READ.reset(token)


async def policy_of(rt: Runtime, tool: str) -> WritePolicy:
    read = _READ.get()
    if read is not None and tool in read:
        return read[tool]
    policy = await _policy_of(rt, tool)
    if read is not None:
        read[tool] = policy
    return policy


async def _policy_of(rt: Runtime, tool: str) -> WritePolicy:
    if rt.tools is not None:
        try:
            data = await rt.tools.tool_policy(tool)
        except (ServiceCallError, ServiceUnreachable) as e:
            raise ToolsUnavailable(
                f"The tools service cannot be reached, so the approvals {tool} needs are unknown. Try again shortly."
            ) from e
        access = str(data["access"])
        approval: dict[str, Any] = data.get("approval") or {}
        return WritePolicy(
            access=access,
            approvers=int(approval.get("approvers") or 1),
            step_up=bool(approval.get("stepUp")) or int(approval.get("approvers") or 1) > 1,
        )
    access = await access_of(rt, tool)
    definition = rt.catalog.tool(tool)
    approvers = definition.approvers if definition else 1
    step_up = bool(definition and definition.step_up) or approvers > 1
    return WritePolicy(access, approvers, step_up=step_up)


async def access_of(rt: Runtime, tool: str) -> str:
    if rt.tools is not None:
        try:
            return await rt.tools.tool_access(tool)
        except (ServiceCallError, ServiceUnreachable) as e:
            # No local fallback: tools-service is the authority on how many approvers a call needs.
            raise ToolsUnavailable(
                f"The tools service cannot be reached, so the approvals {tool} needs are unknown. Try again shortly."
            ) from e
    if tool in WORKFLOW_TOOLS:
        return WORKFLOW_TOOLS[tool]
    definition = rt.catalog.tool(tool)
    return definition.access if definition else "unknown"
