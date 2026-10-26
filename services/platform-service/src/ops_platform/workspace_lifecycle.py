"""The workspace and team danger zones (c-529): who may transfer, leave, close and restore a workspace, and leave and
delete a team, decided by `can()` from the roles the database holds now.

The owner holds `workspace.manage`, the one cell of the built-in role Owner, which Admin's every-cell grid leaves out
(owner, 2026-10-23: "open defaults, can() only"). A transfer goes to an account admin (`access.manage` in every team),
decided by `can()` on the target. The refusals outside `can()` are state invariants (register rows E42 to E44 and the
state lines of the access allowlist): `owner_must_transfer`, `last_admin`, `workspace_closed`, and the delete and
close preconditions. Closing a workspace or deleting a team first asks agents-service what still runs there; with no
answer the action is refused, never taken on an unknown answer.

`WorkspacePurge.once` is the `workspace_lifecycle` background process: it finds workspaces closed longer than the
restore window and purges each in its own tenant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ops_service_kit.errors import Conflict, Forbidden, NotFound, ServiceUnavailable, ValidationFailed
from ops_service_kit.ids import new_id
from ops_service_kit.logging import get_logger

from .store.lifecycle import (
    CLOSED,
    PURGED,
    PURGING,
    LastAdminError,
    LifecycleStore,
    NotOwnerError,
    PurgeStartedError,
    WorkspaceNotActiveError,
)
from .store.members import Actor
from .store.teams import TeamAdminStore
from .team_admin import workspace
from .team_usage import TeamUsage, UsageReader, UsageUnavailable
from .teams import Members

log = get_logger("ops_platform.workspace_lifecycle")


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _owner_must_transfer() -> Conflict:
    return Conflict("The owner transfers the workspace to another account admin first.", code="owner_must_transfer")


def _owner_changed() -> Conflict:
    """A transfer that won the race moved ownership after `can()` let this request in."""
    return Conflict("The workspace has just been transferred; reload to see its owner.", code="owner_changed")


def _unavailable() -> ServiceUnavailable:
    return ServiceUnavailable(
        "What still runs in this team could not be checked. Try again in a moment.", code="usage_unavailable"
    )


def closed() -> Forbidden:
    return Forbidden("This workspace is closed.", code="workspace_closed")


@dataclass
class WorkspaceLifecycle:
    store: LifecycleStore
    teams: TeamAdminStore
    members: Members
    restore_days: int = 30
    team_delete_after_days: int = 30

    async def _is_owner(self, actor: Actor) -> None:
        await self.members.require_admin(workspace(actor), "workspace", "manage")

    async def state(self, tenant_id: str) -> dict[str, Any]:
        """What `/v1/me` says of the workspace: its owner, status and, while closed, when it will be purged."""
        s = await self.store.state(tenant_id)
        purge_after = None
        if s.status == CLOSED and s.closed_at:
            closed_at = datetime.fromisoformat(s.closed_at.replace("Z", "+00:00"))
            purge_after = _iso(closed_at + timedelta(days=self.restore_days))
        return {"ownerUserId": s.owner, "status": s.status, "purgeAfter": purge_after}

    async def open_or_refuse(self, tenant_id: str) -> None:
        if await self.store.status(tenant_id) in (CLOSED, PURGING, PURGED):
            raise closed()

    async def transfer(self, actor: Actor, to: str) -> dict[str, Any]:
        await self._is_owner(actor)
        if to == actor.user_id:
            raise ValidationFailed("Pick another account admin.", code="same_owner")
        try:
            await self.members.require_admin(Actor(actor.tenant_id, "*", to, actor.request_id), "access", "manage")
        except Forbidden as e:
            raise Conflict("Only an account admin can own the workspace.", code="not_an_account_admin") from e
        try:
            await self.store.transfer(
                actor.tenant_id, by=actor.user_id, to=to, at=_iso(datetime.now(UTC)), request_id=actor.request_id
            )
        except NotOwnerError as e:
            raise _owner_changed() from e
        except WorkspaceNotActiveError as e:
            raise closed() from e
        return await self.state(actor.tenant_id)

    async def leave(self, actor: Actor) -> None:
        if (await self.store.state(actor.tenant_id)).owner == actor.user_id:
            raise _owner_must_transfer()
        try:
            await self.store.leave(
                actor.tenant_id, user_id=actor.user_id, at=_iso(datetime.now(UTC)), request_id=actor.request_id
            )
        except NotOwnerError as e:
            raise _owner_must_transfer() from e

    async def refuse_owner(self, tenant_id: str, user_ids: list[str]) -> None:
        """The member routes never remove or demote the owner."""
        if (await self.store.state(tenant_id)).owner in user_ids:
            raise _owner_must_transfer()

    async def _usages(self, tenant_id: str, team_ids: list[str], usage: UsageReader) -> dict[str, TeamUsage]:
        try:
            return {t: await usage.of(tenant_id, t) for t in team_ids}
        except UsageUnavailable as e:
            log.warning("team_usage_unread", extra={"error": str(e)})
            raise _unavailable() from e

    async def close(self, actor: Actor, name: str, usage: UsageReader) -> dict[str, Any]:
        await self._is_owner(actor)
        rows, _, _ = await self.teams.every(actor.tenant_id, statuses=["active", "archived"], page_size=10_000)
        if name.strip() != (await self.store.name(actor.tenant_id)):
            raise ValidationFailed("Type the workspace's name exactly to delete it.", code="name_mismatch")
        found = await self._usages(actor.tenant_id, [str(r["id"]) for r in rows], usage)
        running = sum(u.runs_in_progress for u in found.values())
        if running:
            raise Conflict(
                f"{running} runs are still in progress. Wait for them or cancel them first.", code="runs_in_progress"
            )
        try:
            await self.store.close(
                actor.tenant_id, by=actor.user_id, at=_iso(datetime.now(UTC)), request_id=actor.request_id
            )
        except NotOwnerError as e:
            raise _owner_changed() from e
        except WorkspaceNotActiveError as e:
            raise closed() from e
        return await self.state(actor.tenant_id)

    async def restore(self, actor: Actor) -> dict[str, Any]:
        await self._is_owner(actor)
        try:
            await self.store.restore(actor.tenant_id, by=actor.user_id, request_id=actor.request_id)
        except PurgeStartedError as e:
            raise Conflict("The workspace's records are already being removed.", code="purged") from e
        except WorkspaceNotActiveError as e:
            raise Conflict("The workspace is not closed.", code="not_closed") from e
        return await self.state(actor.tenant_id)

    async def leave_team(self, actor: Actor, team_id: str) -> None:
        try:
            left = await self.store.leave_team(
                actor.tenant_id, team_id, user_id=actor.user_id, at=_iso(datetime.now(UTC)), request_id=actor.request_id
            )
        except LastAdminError as e:
            raise Conflict(
                "You are this team's last admin. Make someone else an admin first.", code="last_admin"
            ) from e
        if not left:
            raise NotFound("team membership")

    async def delete_check(self, actor: Actor, team_id: str, usage: UsageReader) -> dict[str, Any]:
        """What the Delete card shows: whether the team may be deleted now and, if not, each reason."""
        await self.members.require_admin(workspace(actor), "access", "manage")
        state = await self.store.team_state(actor.tenant_id, team_id)
        if state is None:
            raise NotFound("team")
        status, archived_at = state
        days_left = None
        if status == "archived" and archived_at:
            since = datetime.fromisoformat(archived_at.replace("Z", "+00:00"))
            due = since + timedelta(days=self.team_delete_after_days)
            days_left = max(0, -(-int((due - datetime.now(UTC)).total_seconds()) // 86400))
        try:
            found: TeamUsage | None = await usage.of(actor.tenant_id, team_id)
        except UsageUnavailable:
            found = None
        security = team_id == await self.teams.security_team_of(actor.tenant_id)
        can_delete = (
            not security and status == "archived" and days_left == 0 and found is not None and not found.live_workflows
        )
        return {
            "teamId": team_id,
            "status": status,
            "security": security,
            "daysLeft": days_left,
            "usageKnown": found is not None,
            "liveWorkflows": found.live_workflows if found else [],
            "runsInProgress": found.runs_in_progress if found else 0,
            "canDelete": can_delete,
        }

    async def delete_team(self, actor: Actor, team_id: str, usage: UsageReader) -> None:
        await self.members.require_admin(workspace(actor), "access", "manage")
        if team_id == await self.teams.security_team_of(actor.tenant_id):
            raise Conflict("The Security team decides workspace settings and cannot be deleted.", code="security_team")
        state = await self.store.team_state(actor.tenant_id, team_id)
        if state is None:
            raise NotFound("team")
        if state[0] != "archived" or not state[1]:
            raise Conflict("Archive the team before deleting it.", code="not_archived")
        now = datetime.now(UTC)
        cutoff = _iso(now - timedelta(days=self.team_delete_after_days))
        if state[1] > cutoff:
            raise Conflict(
                f"A team is deleted only after {self.team_delete_after_days} days archived.",
                code="archived_too_recently",
            )
        found = (await self._usages(actor.tenant_id, [team_id], usage))[team_id]
        if found.live_workflows:
            raise Conflict(
                "Pause or move its live workflows first: " + ", ".join(found.live_workflows) + ".",
                code="live_workflows",
                details={"liveWorkflows": found.live_workflows},
            )
        done = await self.store.delete_team(
            actor.tenant_id,
            team_id,
            by=actor.user_id,
            archived_before=cutoff,
            at=_iso(now),
            request_id=actor.request_id,
        )
        if not done:
            raise Conflict("Archive the team before deleting it.", code="not_archived")


@dataclass
class WorkspacePurge:
    store: LifecycleStore
    restore_days: int = 30

    async def once(self) -> int:
        purged = 0
        for tenant_id in await self.store.purge_due(restore_days=self.restore_days):
            if await self.store.purge(tenant_id, at=_iso(datetime.now(UTC)), request_id=new_id("req")):
                purged += 1
        return purged
