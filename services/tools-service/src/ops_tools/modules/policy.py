"""The team's publish-review mode for tool modules: the tenant's `publishReview` policy, read live from
platform-service on each decision, so a team admin's change applies at once. Read with this service's
token for the tenant (`settings:view`), never cached and never taken from a caller's token. A policy that cannot be
read counts as "always", so a failed read never lets a version go live unreviewed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ops_access import BY_KEY, Access, effective_answer, publish_mode, team_on
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
    def __init__(self, platform: ServiceClient | None = None) -> None:
        """The team's approval settings for agent changes (`appChanges`, `appChangesByApp`), read live from
        platform-service on each call with this service's `settings:view` token for the tenant, as PublishPolicy
        reads publishReview. Without `platform` no team has set anything."""
        self.platform = platform

    async def levels(self, tenant_id: str, team_id: str | None) -> tuple[Any, dict[str, Any]]:
        """(team level, per-app levels) for `team_id`. The team level is None when the policy cannot be read, which
        `effective_answer` counts as waiting, so a failed read never lets a write through unapproved."""
        if self.platform is None:
            return {}, {}
        try:
            team = await self.platform.get("/v1/policies/appChanges", tenant=tenant_id)
            by_app = await self.platform.get("/v1/policies/appChangesByApp", tenant=tenant_id)
            of_team = dict(team.get("value") or {}).get(team_id) if team_id else None
            apps = dict(by_app.get("value") or {}).get(team_id) if team_id else None
            return (of_team or {}), dict(apps or {})
        except (ServiceCallError, ServiceUnreachable, KeyError, TypeError, ValueError, AttributeError):
            return None, {}

    async def answer(
        self,
        tenant_id: str,
        team_id: str | None,
        module: dict[str, Any] | None,
        *,
        access: str,
        setting: bool | None,
        approvers: int = 1,
        channel: str = "chat",
        test_account: bool = False,
        levels: tuple[Any, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """The one answer to "does this call wait, and who answers": the tool's own setting, its app's entry and the
        team's, through `effective_answer`. Everything that shows or enforces a wait calls here."""
        team, by_app = levels or await self.levels(tenant_id, team_id)
        app = next((by_app[i] for i in sorted(app_ids(module) if module else ()) if i in by_app), None)
        mode = {True: "reviewer", False: "none"}.get(setting) if setting is not None else None  # type: ignore[arg-type]
        tool = {"access": access, "approvalMode": mode, "reviewerRole": None, "approvers": approvers}
        return effective_answer(tool=tool, app=app, team=team, channel=channel, test_account=test_account)


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
