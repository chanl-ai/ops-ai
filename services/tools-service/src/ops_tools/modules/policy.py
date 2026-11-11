"""The team's publish-review mode for tool modules: the tenant's `publishReview` policy, read live from
platform-service on each decision, so a team admin's change applies at once. Read with this service's
token for the tenant (`settings:view`), never cached and never taken from a caller's token. A policy that cannot be
read counts as "always", so a failed read never lets a version go live unreviewed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ops_access import BY_KEY, Access, publish_mode, team_names, team_on, team_writes_need_approval
from ops_identity import ActingForPerson, Principal, ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.errors import Forbidden

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
        """The team's `toolWritesNeedApproval`, read live from platform-service on each call with this
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

    async def apps(self, tenant_id: str, team_id: str | None) -> list[str] | None:
        """The apps whose writes `team_id` has wait (appWritesNeedApproval), by the ids the Apps page shows. None
        when the policy cannot be read, which the gateway counts as every app, so a failed read never lets a write
        through unapproved."""
        try:
            data = await self.platform.get("/v1/policies/appWritesNeedApproval", tenant=tenant_id)
            return team_names(data.get("value"), team_id)
        except (ServiceCallError, ServiceUnreachable, KeyError, TypeError, ValueError, AttributeError):
            return None

    async def change_without_asking(self, tenant_id: str, team_id: str | None) -> list[str] | None:
        """The apps whose "Ask before changes" `team_id`'s admin switched off (appsChangeWithoutAsking), by the ids
        the Apps page shows; every other app's writes ask the person in chat first. None when the policy cannot be
        read, which counts as no app listed, so a failed read never stops the asking."""
        try:
            data = await self.platform.get("/v1/policies/appsChangeWithoutAsking", tenant=tenant_id)
            return team_names(data.get("value"), team_id)
        except (ServiceCallError, ServiceUnreachable, KeyError, TypeError, ValueError, AttributeError):
            return None


def approves_own_writes(access: Access, p: Principal) -> bool:
    """Whether the caller is their own approver: a person holding reviews.decide in the team they
    act in, as one who decides the team's reviews, while the requesterMayDecide policy lets an asker decide (off, the
    four-eyes rule, someone else decides). A service or an API key never is."""
    return p.kind == "person" and access.may(p, "reviews", "decide", requested_by=(p.email,))


def asker_refusal(
    access: Access, asker: ActingForPerson, tenant_id: str, approvers: list[str], *, may_decide: bool
) -> Forbidden | None:
    """The refusal `can` gives when an approval names the person the call acts for and requesterMayDecide, read at the
    call (`may_decide`), does not let an asker decide; None when someone else approved or the policy allows it. Only
    the separation-of-duties part counts here: the approver's role was checked when the approval was given."""
    if asker.email.casefold() not in {a.casefold() for a in approvers}:
        return None
    person = Principal(
        kind="person",
        sub=asker.sub,
        email=asker.email,
        name=asker.name,
        tenant_id=tenant_id,
        team_id=asker.team_id,
        team_ids=[asker.team_id] if asker.team_id else [],
        roles={},
        scopes=[],
        auth_method="session",
        policies={"requesterMayDecide": may_decide},
    )
    try:
        access.can(person, "reviews", "decide", team=asker.team_id, requested_by=[asker.email], what="this write")
    except Forbidden as refused:
        return refused if refused.code == "own_request" else None
    return None


def app_ids(module: dict[str, Any]) -> set[str]:
    """The ids a module's app goes by on the Apps page: its plugin's card, its connection, or the module itself."""
    template = str(module.get("template_id") or "")
    ids = {f"module:{module['id']}"}
    if template.startswith("plugin:"):
        # A plugin's module holds its plugin in the template slot, `plugin:<id>`, the same id as its app card.
        ids.add(template)
    if module.get("connection_id"):
        ids.add(str(module["connection_id"]))
    return ids


class CheckBeforeSend:
    def __init__(self, platform: ServiceClient) -> None:
        """The team's `checkBeforeSend`, read live from platform-service on each write with this service's
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
        """The tenant's `requesterMayDecide`, read live from platform-service, for decisions this service
        applies on a workflow's behalf (a tool access request), where the deciding person's token is not here.
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
