"""The team's publish-review mode for tool modules: the tenant's `publishReview` policy, read live from
platform-service on each decision, so a team admin's change applies at once. Read with this service's
token for the tenant (`settings:view`), never cached and never taken from a caller's token. A policy that cannot be
read counts as "always", so a failed read never lets a version go live unreviewed."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal, cast

from ops_access import Access, EffectiveAnswer, effective_answer, publish_mode, team_on
from ops_identity import Principal, ServiceCallError, ServiceClient, ServiceUnreachable, own_request_answer
from ops_service_kit.errors import Forbidden
from ops_service_kit.http import Json
from ops_service_kit.narrow import json_object

from ..store.modules import Module, ModuleColumns, Operation

# The area platform-service's access check is asked about for a tool access request or write approval: every decision
# here is a review, as `can()` asks it (`BY_AREA_TAKES`).
REVIEWS = "reviews"

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
            modes: Json = dict(data.get("value") or {})
            mode = publish_mode(modes, team_id, "tools")
            if mode not in MODES:
                raise ValueError(mode)
            return ToolsMode(mode)
        except (ServiceCallError, ServiceUnreachable, KeyError, TypeError, ValueError, AttributeError):
            return ToolsMode("always", unreadable=True)


# Where `levels` keeps the Security team's floor (approvalsFloor) in the team level; no appChanges field has this name.
FLOOR = "_approvalsFloor"
# appChanges switches whose off value lets a write run that would otherwise wait.
LOOSENING = frozenset({"makersAsk", "testRunsAsk"})


class WriteApprovals:
    def __init__(self, platform: ServiceClient | None = None) -> None:
        """The team's approval settings for agent changes (`appChanges`, `appChangesByApp`), read live from
        platform-service on each call with this service's `settings:view` token for the tenant, as PublishPolicy
        reads publishReview. Without `platform` the settings cannot be read, which is answered as a failed read."""
        self.platform = platform

    async def levels(self, tenant_id: str, team_id: str | None) -> tuple[Any, Json]:
        """(team level, per-app levels) for `team_id`. The team level is None when the policy cannot be read: the
        gateway then refuses the write (approval_rules_unavailable) and `effective_answer` shows it as waiting."""
        if self.platform is None:
            return None, {}
        try:
            team = await self.platform.get("/v1/policies/appChanges", tenant=tenant_id)
            by_app = await self.platform.get("/v1/policies/appChangesByApp", tenant=tenant_id)
            held = dict(team.get("value") or {})
            # `*` is the workspace's own value (a new workspace's makersAsk off); a team's saved part wins over it.
            workspace = dict(held.get("*") or {})
            if team_id:
                of_team = {**workspace, **dict(held.get(team_id) or {})}
            else:
                # A caller naming no team waits where the workspace asks, and keeps every wait it had: the switches
                # that only let writes through (makers' asks off, test runs not asking) are not taken from `*`.
                of_team = {k: v for k, v in workspace.items() if not (k in LOOSENING and v is False)}
            apps = dict(by_app.get("value") or {}).get(team_id) if team_id else None
        except (ServiceCallError, ServiceUnreachable, KeyError, TypeError, ValueError, AttributeError):
            return None, {}
        # The Security team's floor rides in the team level under FLOOR, only when it locks something, so `answer`
        # hands it to `effective_answer`. A floor that cannot be read counts as the strictest one: every write waits
        # for a reviewer rather than running past a lock it could not see.
        try:
            floor = json_object((await self.platform.get("/v1/policies/approvalsFloor", tenant=tenant_id)).get("value"))
        except (ServiceCallError, ServiceUnreachable, KeyError, TypeError, ValueError, AttributeError):
            floor = {"appChanges": "reviewer"}
        return ({**(of_team or {}), FLOOR: floor} if floor else (of_team or {})), dict(apps or {})

    async def answer(
        self,
        tenant_id: str,
        team_id: str | None,
        module: Module | None,
        *,
        access: str,
        setting: str | bool | None,
        reviewer_role: str | None = None,
        approvers: int = 1,
        channel: str = "chat",
        test_account: bool = False,
        levels: tuple[Any, Json] | None = None,
        tool: str | None = None,
        draft: bool = False,
    ) -> EffectiveAnswer:
        """The one answer to "does this call wait, and who answers": the tool's own setting, its app's entry and the
        team's, through `effective_answer`. Everything that shows or enforces a wait calls here.

        `tool` is the tool's name. An admin's answer for that tool, kept in the team's `appChangesByApp` under
        `tool:<name>`, replaces the tool's own setting, so a plugin tool whose manifest asks first (its module row
        cannot be edited) is still changed by a team admin."""
        team, by_app = levels or await self.levels(tenant_id, team_id)
        floor: Any = None
        if isinstance(team, dict) and FLOOR in team:
            team = dict(cast(Json, team))
            floor = team.pop(FLOOR)
        app = next((by_app[i] for i in sorted(app_ids(module) if module else ()) if i in by_app), None)
        # `setting` is the tool's own mode (see `tool_mode`). A bare True or False is a stored requires_approval, which
        # cannot be told from the old default, so it is no override: the app and the team decide.
        mode = setting if isinstance(setting, str) else None
        # A new workspace turns makers' asks off (appChanges makersAsk false): a wait the manifest or seed declared
        # stops being the tool's answer, so the app and team decide; an answer a person set on a tool still holds.
        if isinstance(team, dict) and cast(Json, team).get("makersAsk") is False and maker_asks(module, tool):
            mode = None
        admin: Any = by_app.get(tool_key(tool)) if tool else None
        if isinstance(admin, dict):
            held = cast(Json, admin)
            if held.get("answer") in ("none", "person", "reviewer"):
                mode, reviewer_role = str(held["answer"]), cast(str | None, held.get("reviewerRole")) or reviewer_role
        own: Json = {
            "access": access,
            "approvalMode": mode,
            "reviewerRole": reviewer_role,
            "approvers": approvers,
            "draft": draft,
        }
        return effective_answer(tool=own, app=app, team=team, channel=channel, test_account=test_account, floor=floor)


def maker_asks(module: Module | None, tool: str | None) -> bool:
    """Whether the tool's reviewer answer is its maker's: a plugin's operation (its row has no editor, so the answer is
    the manifest's) or a seeded one that declared the wait (requires_approval true beside it)."""
    if not module or not tool:
        return False
    operations = module["operations"]
    op = next((o for o in operations if o.get("name") == tool), None)
    if op is None or op.get("approval_mode") != "reviewer":
        return False
    return str(module.get("template_id") or "").startswith("plugin:") or op.get("requires_approval") is True


def tool_key(tool: str) -> str:
    """Where a team admin's answer for one tool lives in `appChangesByApp`; no app id starts with `tool:`."""
    return f"tool:{tool}"


def tool_mode(op: Operation) -> str | None:
    """The tool's own answer (none, person or reviewer) from its operation row: its approval_mode only. The older
    requires_approval flag is not read: a stored true cannot be told from the old default, so it follows the tool's
    app, then the team."""
    mode = op.get("approval_mode")
    if mode in ("none", "person", "reviewer"):
        return str(mode)
    return None


def approves_own_writes(access: Access, p: Principal) -> bool:
    """Whether the caller is their own approver by their token: a person holding reviews.decide and Approvals decide in
    the team they act in. The gateway confirms it live (`OwnRequests`) before a write skips its approval. A service or
    an API key never is."""
    return p.kind == "person" and access.may(p, "reviews", "decide", requested_by=(p.email,))


def app_ids(module: ModuleColumns) -> set[str]:
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


class OwnRequests:
    def __init__(self, platform: ServiceClient | None) -> None:
        """Whether a request's asker may decide it themselves, asked of platform-service's access check
        (POST /v1/access/check, this service's `access:view` token for the tenant and the deciding team) when the
        decision is made: the asker holds Approvals decide there now, whatever a token minted earlier says. With no
        platform-service the cell cannot be asked, so the asker is refused, as with a failed read."""
        self.platform = platform

    async def refusal(
        self, tenant_id: str, team_id: str | None, asker: str, deciders: Iterable[str | None], *, what: str = "this"
    ) -> Forbidden | None:
        """403 `own_request` when one of `deciders` is `asker` (an email) and the asker may not decide their own
        request in `team_id`; None otherwise. Only that refusal counts: the decider's role was checked where the
        decision was made. A check that cannot be made refuses, so a failed read never lets someone approve their own
        request."""
        if not asker or asker.casefold() not in {str(d).casefold() for d in deciders if d}:
            return None
        fallback = Forbidden(f"You asked for {what}, so someone else has to decide it.", code="own_request")
        if self.platform is None or team_id is None:
            return fallback
        data = await own_request_answer(self.platform, tenant=tenant_id, team=team_id, email=asker)
        if data is None:
            return fallback
        refused = json_object(data.get("refusedBy"))
        if refused.get("code") == "own_request":
            return Forbidden(str(refused.get("reason") or fallback.message), code="own_request")
        return None
