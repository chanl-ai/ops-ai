"""What tools-service does with platform-service's events: each event's handler, with the right its caller
must hold, served at `POST /v1/platform-events` by `ops_access.platform_events`."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ops_access.platform_events import MEMBER_REMOVED, TEAM_CREATED, Handler
from ops_policy import CredentialStore

from .defaults import ensure_defaults
from .store.connections import ConnectionStore, held_of
from .store.modules import ModuleStore
from .store.team_defaults import TeamDefaults


def member_removed_handlers(store: ConnectionStore, credentials: CredentialStore) -> dict[str, Handler]:
    """A leaver's own sign-ins go, and what they held goes from the credential store with them."""

    async def forget(tenant_id: str, team_id: str, payload: dict[str, Any]) -> int:
        rows = await store.forget_person(tenant_id, team_id, str(payload["personId"]))
        for ref, context in held_of(tenant_id, rows):
            await credentials.delete(ref, context=context)
        return len(rows)

    return {MEMBER_REMOVED: Handler("connections", "delete", forget)}


def team_created_handlers(modules: ModuleStore, defaults: TeamDefaults) -> dict[str, Handler]:
    """A new team gets this service's defaults, its built-in apps, before anyone opens it."""

    async def provision(tenant_id: str, team_id: str, _: dict[str, Any]) -> int:
        at = datetime.now(UTC)
        return int(await ensure_defaults(modules, defaults, tenant_id=tenant_id, team_id=team_id, at=at))

    return {TEAM_CREATED: Handler("tools", "create", provision)}
