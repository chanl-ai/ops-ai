"""Creating, listing and revoking API keys (I4): admins of the key's team only. A key is `ok_<id>.<secret>`; the
secret is 32 random bytes, returned once from creation and stored as its SHA-256. Which methods a key's scopes allow
is enforced where the key is used, by `ops_identity` from the HTTP method (I9), not here."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ops_service_kit.errors import NotFound
from ops_service_kit.ids import new_id

from .store.keys import KeyStore
from .store.members import Actor
from .teams import Members


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def shown(row: dict[str, Any]) -> dict[str, Any]:
    status = "revoked" if row["revoked_at"] else "disabled" if row["disabled_at"] else "active"
    out = {
        "id": row["id"],
        "name": row["name"],
        "prefix": row["prefix"],
        "scopes": list(row["scopes"]),
        "createdBy": row["created_by"],
        "createdAt": row["created_at"],
        "lastUsedAt": row["last_used_at"],
        "expiresAt": row["expires_at"],
        "team": row["team"],
        "status": status,
    }
    return out


@dataclass
class ApiKeys:
    store: KeyStore
    members: Members

    async def list(self, actor: Actor) -> list[dict[str, Any]]:
        await self.members.require_admin(actor)
        return [shown(r) for r in await self.store.list(actor.tenant_id, actor.team_id)]

    async def create(self, actor: Actor, name: str, scopes: list[str], expires_in_days: int | None) -> dict[str, Any]:
        await self.members.require_admin(actor)
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
        )
        return {"key": shown(row), "secret": f"ok_{key_id}.{secret}"}

    async def revoke(self, actor: Actor, key_id: str) -> dict[str, Any]:
        await self.members.require_admin(actor)
        row = await self.store.revoke(actor, key_id, at=_iso(datetime.now(UTC)))
        if row is None:
            raise NotFound("This team has no such key.")
        return shown(row)
