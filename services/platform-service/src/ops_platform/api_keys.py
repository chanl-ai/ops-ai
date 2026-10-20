"""Creating, listing and revoking API keys (I4): admins of the key's team only. A key is `ok_<id>.<secret>`; the
secret is 32 random bytes, returned once from creation and stored as its SHA-256. Which methods a key's scopes allow
is enforced where the key is used, by `ops_identity` from the HTTP method (I9), not here."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ops_service_kit.errors import NotFound, ValidationFailed
from ops_service_kit.ids import new_id

from .store.keys import KeyStore
from .store.members import Actor
from .teams import Members


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def target_of(row: dict[str, Any]) -> dict[str, Any] | None:
    if not row["target_kind"]:
        return None
    return {"kind": row["target_kind"], "id": row["target_id"], "version": row["target_version"]}


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
        "target": target_of(row),
    }
    return out


def summary(row: dict[str, Any]) -> dict[str, Any]:
    """A key as another service lists it: what it serves and whether it works, never its creator or secret."""
    out = shown(row)
    return {k: out[k] for k in ("id", "name", "prefix", "status", "target", "lastUsedAt", "expiresAt", "createdAt")} | {
        "teamId": row["team_id"]
    }


@dataclass
class ApiKeys:
    store: KeyStore
    members: Members

    async def list(self, actor: Actor) -> list[dict[str, Any]]:
        await self.members.require_admin(actor)
        return [shown(r) for r in await self.store.list(actor.tenant_id, actor.team_id)]

    async def create(
        self,
        actor: Actor,
        name: str,
        scopes: list[str],
        expires_in_days: int | None,
        target: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self.members.require_admin(actor, "access", "create")
        if target is not None and "write" not in scopes:
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

    async def revoke(self, actor: Actor, key_id: str) -> dict[str, Any]:
        await self.members.require_admin(actor, "access", "delete")
        row = await self.store.revoke(actor, key_id, at=_iso(datetime.now(UTC)))
        if row is None:
            raise NotFound("This team has no such key.")
        return shown(row)

    async def summaries(self, tenant_id: str) -> list[dict[str, Any]]:
        return [summary(r) for r in await self.store.every(tenant_id)]
