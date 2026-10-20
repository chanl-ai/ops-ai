"""Teams as workspace admins manage them (c-198): list every team, create one with its first admin, rename, archive
and restore. A workspace admin holds `access.manage` in every team: an Admin role assignment in team `*` (owner,
2026-10-17). `can()` decides it on the workspace (`*`) as the team, so an admin of one team is refused and no new grid
cell is needed; listing needs `access.view` there. Team admins keep managing members and roles on the member routes.
The Security team cannot be archived: workspace settings are decided there.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ops_access import ANY_TEAM
from ops_service_kit.errors import Conflict, NotFound, ValidationFailed
from ops_service_kit.http import paged

from .store.members import Actor
from .store.teams import ACTIVE, ARCHIVED, TeamAdminStore, TeamNameTakenError
from .store.workspace import TeamNotUsableError, WorkspaceStore
from .teams import Members


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _taken() -> Conflict:
    return Conflict("Another team in this workspace has that name.", code="team_name_taken")


def workspace(actor: Actor) -> Actor:
    """The actor acting on the workspace rather than one team: rights are read in `*`."""
    return Actor(actor.tenant_id, ANY_TEAM, actor.user_id, actor.request_id)


@dataclass
class TeamAdmin:
    store: TeamAdminStore
    members: Members
    workspace_store: WorkspaceStore

    async def workspace_teams(self, actor: Actor) -> dict[str, Any]:
        await self.members.require_admin(workspace(actor), "access", "view")
        return await self.workspace_teams_of(actor.tenant_id)

    async def workspace_teams_of(self, tenant_id: str) -> dict[str, Any]:
        """No person to check: the caller is a service whose `settings:view` scope the route has checked."""
        found = await self.workspace_store.read(tenant_id)
        return {"securityTeam": found.security_team, "defaultTeam": found.default_team}

    async def rename_workspace(self, actor: Actor, name: str) -> dict[str, Any]:
        """Workspace admins only; every person's next `/v1/me` names the workspace with it."""
        await self.members.require_admin(workspace(actor), "access", "manage")
        named = await self.workspace_store.rename(
            actor.tenant_id, name.strip(), by=actor.user_id, request_id=actor.request_id
        )
        return {"id": actor.tenant_id, "name": named}

    async def set_workspace_teams(self, actor: Actor, security_team: str, default_team: str | None) -> dict[str, Any]:
        await self.members.require_admin(workspace(actor), "access", "manage")
        try:
            saved = await self.workspace_store.set(
                actor.tenant_id, security_team=security_team, default_team=default_team, by=actor.user_id,
                at=_iso(datetime.now(UTC)), request_id=actor.request_id,
            )  # fmt: skip
        except TeamNotUsableError as e:
            raise ValidationFailed("Pick active teams of this workspace.", code="team_not_usable") from e
        return {"securityTeam": saved.security_team, "defaultTeam": saved.default_team}

    async def every(
        self, actor: Actor, *, statuses: list[str], search: str, page: int, page_size: int
    ) -> dict[str, Any]:
        await self.members.require_admin(workspace(actor), "access", "view")
        rows, total, answered = await self.store.every(
            actor.tenant_id, statuses=statuses, search=search, page=page, page_size=page_size
        )
        return paged(rows, total, answered, page_size)

    async def create(self, actor: Actor, name: str, admin_email: str) -> dict[str, Any]:
        await self.members.require_admin(workspace(actor), "access", "manage")
        try:
            team_id = await self.store.create(
                actor.tenant_id,
                name=name.strip(),
                admin_email=admin_email,
                by=actor.user_id,
                at=_iso(datetime.now(UTC)),
                request_id=actor.request_id,
            )
        except TeamNameTakenError as e:
            raise _taken() from e
        if team_id is None:
            raise NotFound("person")
        return await self._read(actor, team_id)

    async def rename(self, actor: Actor, team_id: str, name: str) -> dict[str, Any]:
        await self.members.require_admin(workspace(actor), "access", "manage")
        try:
            done = await self.store.rename(
                actor.tenant_id, team_id, name.strip(), by=actor.user_id, at=_iso(datetime.now(UTC)),
                request_id=actor.request_id,
            )  # fmt: skip
        except TeamNameTakenError as e:
            raise _taken() from e
        if not done:
            raise NotFound("team")
        return await self._read(actor, team_id)

    async def set_status(self, actor: Actor, team_id: str, archived: bool) -> dict[str, Any]:
        await self.members.require_admin(workspace(actor), "access", "manage")
        if archived and team_id == await self.store.security_team_of(actor.tenant_id):
            raise Conflict("The Security team decides workspace settings and cannot be archived.", code="security_team")
        done = await self.store.set_status(
            actor.tenant_id, team_id, ARCHIVED if archived else ACTIVE, by=actor.user_id, at=_iso(datetime.now(UTC)),
            request_id=actor.request_id,
        )  # fmt: skip
        if not done:
            raise NotFound("team")
        return await self._read(actor, team_id)

    async def _read(self, actor: Actor, team_id: str) -> dict[str, Any]:
        found = await self.store.one(actor.tenant_id, team_id)
        if found is None:
            raise NotFound("team")
        return found
