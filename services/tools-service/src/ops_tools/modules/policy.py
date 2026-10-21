"""The team's publish-review mode for tool modules (c-214): the tenant's `publishReview` policy, read live from
platform-service on each decision, so a team admin's change applies at once. Read with this service's
token for the tenant (`settings:view`), never cached and never taken from a caller's token. A policy that cannot be
read counts as "always", so a failed read never lets a version go live unreviewed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ops_access import BY_KEY, publish_mode, team_on, team_writes_need_approval
from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable

Mode = Literal["always", "major", "never"]
MODES: tuple[Mode, ...] = ("always", "major", "never")
# The identity headers a caller sent; agents-service resolves them exactly as tools-service did.
FORWARDED = ("authorization", "x-api-key", "x-dev-user")


@dataclass(frozen=True)
class ToolsMode:
    mode: Mode
    # Set when the policy could not be read and the mode fell back to "always".
    unreadable: bool = False


class PublishPolicy:
    def __init__(self, platform: ServiceClient) -> None:
        """`platform` calls platform-service as this service with `settings:view`, naming the tenant on each call."""
        self.platform = platform

    async def mode(self, tenant_id: str, team_id: str) -> ToolsMode:
        try:
            data = await self.platform.get("/v1/policies/publishReview", tenant=tenant_id)
            modes: dict[str, Any] = dict(data.get("value") or {})
            mode = publish_mode(modes, team_id, "tools")
            if mode not in MODES:
                raise ValueError(mode)
            return ToolsMode(mode)
        except (ServiceCallError, ServiceUnreachable, KeyError, TypeError, ValueError, AttributeError):
            return ToolsMode("always", unreadable=True)


class WriteApprovals:
    def __init__(self, platform: ServiceClient) -> None:
        """The team's `toolWritesNeedApproval` (c-219), read live from platform-service on each call with this
        service's `settings:view` token for the tenant, as PublishPolicy reads publishReview."""
        self.platform = platform

    async def all_writes(self, tenant_id: str, team_id: str | None) -> bool:
        """Whether every tool write by `team_id` waits for approval. A policy that cannot be read counts as on, so a
        failed read never lets a write through unapproved."""
        try:
            data = await self.platform.get("/v1/policies/toolWritesNeedApproval", tenant=tenant_id)
            return team_writes_need_approval(dict(data.get("value") or {}), team_id)
        except (ServiceCallError, ServiceUnreachable, KeyError, TypeError, ValueError, AttributeError):
            return True


class CheckBeforeSend:
    def __init__(self, platform: ServiceClient) -> None:
        """The team's `checkBeforeSend` (c-300), read live from platform-service on each write with this service's
        `settings:view` token for the tenant, as WriteApprovals reads toolWritesNeedApproval."""
        self.platform = platform

    async def on(self, tenant_id: str, team_id: str | None) -> bool:
        """Whether `team_id`'s writes are checked before they go out. A policy that cannot be read counts as on, so a
        failed read never lets a write skip its check."""
        try:
            data = await self.platform.get("/v1/policies/checkBeforeSend", tenant=tenant_id)
            return team_on(data.get("value"), team_id)
        except (ServiceCallError, ServiceUnreachable, KeyError, TypeError, ValueError, AttributeError):
            return True


class RequesterMayDecide:
    def __init__(self, platform: ServiceClient | None, *, dev: dict[str, Any] | None = None) -> None:
        """The tenant's `requesterMayDecide` (c-186), read live from platform-service, for decisions this service
        applies on a workflow's behalf (a tool access request, c-257), where the deciding person's token is not here.
        With no platform-service (dev sign-in) it is the dev policies (OPS_DEV_POLICIES) at their open default, the
        value a dev caller's own identity carries to every other decision."""
        self.platform = platform
        self.dev = dev or {}

    async def allowed(self, tenant_id: str) -> bool:
        """Whether whoever asked may also decide. A policy that cannot be read counts as off: a person never decides
        their own request because a read failed."""
        if self.platform is None:
            return self.dev.get("requesterMayDecide", BY_KEY["requesterMayDecide"].default) is True
        try:
            data = await self.platform.get("/v1/policies/requesterMayDecide", tenant=tenant_id)
            return data.get("value") is True
        except (ServiceCallError, ServiceUnreachable, KeyError, TypeError, ValueError, AttributeError):
            return False
