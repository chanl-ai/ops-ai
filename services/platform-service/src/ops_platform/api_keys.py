"""Creating, listing and revoking API keys (I4): admins of the key's team only. A key is `ok_<id>.<secret>`; the
secret is 32 random bytes, returned once from creation and stored as its SHA-256. Which methods a key's scopes allow
is enforced where the key is used, by `ops_identity` from the HTTP method (I9), not here."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TypedDict

from ops_service_kit.errors import NotFound, ValidationFailed
from ops_service_kit.http import Json
from ops_service_kit.ids import new_id
from ops_service_kit.listing import ListParams
from ops_store.listing import ListPage

from .store.key_events import status_of
from .store.keys import KeyRow, KeyStore
from .store.members import Actor
from .teams import Members


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class KeyTarget(TypedDict):
    kind: str
    id: str | None
    version: int | None


class KeyView(TypedDict):
    """A key as `ApiKeyOut` sends it; never its secret."""

    id: str
    name: str
    prefix: str
    scopes: list[str]
    createdBy: str
    createdAt: str
    lastUsedAt: str | None
    expiresAt: str | None
    team: str
    status: str
    target: KeyTarget | None


class KeySummary(TypedDict):
    """A key as `ApiKeySummary` sends it to another service."""

    id: str
    name: str
    prefix: str
    status: str
    target: KeyTarget | None
    lastUsedAt: str | None
    expiresAt: str | None
    createdAt: str
    teamId: str
    revision: int


class KeyCreated(TypedDict):
    key: KeyView
    # Shown once, never stored or sent again.
    secret: str


def target_of(row: KeyRow) -> KeyTarget | None:
    if not row.target_kind:
        return None
    return {"kind": row.target_kind, "id": row.target_id, "version": row.target_version}


def shown(row: KeyRow) -> KeyView:
    status = status_of(row.revoked_at, row.disabled_at)
    out: KeyView = {
        "id": row.id,
        "name": row.name,
        "prefix": row.prefix,
        "scopes": list(row.scopes),
        "createdBy": row.created_by,
        "createdAt": row.created_at,
        "lastUsedAt": row.last_used_at,
        "expiresAt": row.expires_at,
        "team": row.team,
        "status": status,
        "target": target_of(row),
    }
    return out


def summary(row: KeyRow) -> KeySummary:
    """A key as another service lists it: what it serves and whether it works, never its creator or secret."""
    out = shown(row)
    return {
        "id": out["id"],
        "name": out["name"],
        "prefix": out["prefix"],
        "status": out["status"],
        "target": out["target"],
        "lastUsedAt": out["lastUsedAt"],
        "expiresAt": out["expiresAt"],
        "createdAt": out["createdAt"],
        "teamId": row.team_id,
        "revision": row.revision,
    }


@dataclass
class ApiKeys:
    store: KeyStore
    members: Members

    async def list(self, actor: Actor, params: ListParams) -> ListPage:
        """The team's keys on the shared list contract; `targetKind` and `targetId` keep the keys made for one target
        (an MCP link's Keys tab)."""
        await self.members.require_admin(actor)
        page = await self.store.page(actor.tenant_id, actor.team_id, params)
        page["data"] = [dict(shown(KeyRow.model_validate(r))) for r in page["data"]]
        return page

    async def create(
        self,
        actor: Actor,
        name: str,
        scopes: list[str],
        expires_in_days: int | None,
        target: Json | None = None,
    ) -> KeyCreated:
        await self.members.require_admin(actor, "access", "create")
        if target is not None and target["kind"] == "mcp_link" and ("write" in scopes or target.get("version")):
            # A key opens an MCP link for a system with no person behind it, so it reads only (decision D11).
            raise ValidationFailed("A key for an MCP link reads only; leave the write scope off.")
        if target is not None and target["kind"] != "mcp_link" and "write" not in scopes:
            # Starting a run is a write; a scoped key without it could never start what it names.
            raise ValidationFailed("A key that starts an agent or workflow needs the write scope.")
        if target is not None and target["kind"] == "agent" and target.get("version") is not None:
            raise ValidationFailed("A key for an agent serves its latest published version; it cannot pin one.")
        now = datetime.now(UTC)
        key_id, secret = new_id("key"), secrets.token_urlsafe(32)
        row = await self.store.create(
            actor,
            key_id=key_id,
            name=name,
            secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
            scopes=sorted(set(scopes), key=["read", "write"].index),
            expires_at=_iso(now + timedelta(days=expires_in_days)) if expires_in_days else None,
            at=_iso(now),
            target=target,
        )
        return {"key": shown(row), "secret": f"ok_{key_id}.{secret}"}

    async def revoke(self, actor: Actor, key_id: str) -> KeyView:
        await self.members.require_admin(actor, "access", "delete")
        row = await self.store.revoke(actor, key_id, at=_iso(datetime.now(UTC)))
        if row is None:
            raise NotFound("This team has no such key.")
        return shown(row)

    async def summaries(self, tenant_id: str) -> list[KeySummary]:
        return [summary(r) for r in await self.store.every(tenant_id)]
