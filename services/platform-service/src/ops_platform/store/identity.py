"""Who a person or key is, and their sessions.

Lookups that find the tenant (a user by email, a session by id, a key by prefix) run in `system_tx`; everything after
runs in `tenant_tx` for that tenant. Refresh rotation is a compare-and-set on the stored hash, so two refreshes racing
on one token cannot both win. Sign-in, sign-out and a revocation for refresh-token reuse each write their audit entry
in the same transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import sqlalchemy as sa

from ops_access import active
from ops_service_kit.ids import now_iso
from ops_store import Guarantee

from .audit import record
from .roles import RoleStore, version_in
from .tables import api_keys, members, sessions, teams, tenants, users
from .tenancy import TenantDb


@dataclass(frozen=True)
class User:
    tenant_id: str
    id: str
    email: str
    name: str


@dataclass(frozen=True)
class SessionRef:
    tenant_id: str
    user_id: str
    id: str


@dataclass(frozen=True)
class SessionMethod:
    """How a session started: `auth_method` (dev, password, oidc, saml) and the provider for an SSO one."""

    auth_method: str
    provider_id: str | None


@dataclass(frozen=True)
class Key:
    id: str
    tenant_id: str
    team_id: str
    secret_hash: str
    scopes: list[str]
    created_by: str
    usable: bool


class IdentityStore:
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION, Guarantee.RLS})

    def __init__(self, db: TenantDb) -> None:
        self.db = db

    @classmethod
    def open(cls, url: str) -> IdentityStore:
        return cls(TenantDb.open(url))

    async def close(self) -> None:
        await self.db.engine.dispose()

    async def users_by_email(self, email: str) -> list[User]:
        q = sa.text("SELECT tenant_id, id, email, name FROM platform_users_by_email(:e)")
        async with self.db.system_tx() as c:
            return [User(*row) for row in (await c.execute(q, {"e": email})).all()]

    async def user(self, tenant_id: str, user_id: str) -> User | None:
        q = sa.select(users.c.tenant_id, users.c.id, users.c.email, users.c.name).where(
            users.c.id == user_id, users.c.status == "active"
        )
        async with self.db.tenant_tx(tenant_id) as c:
            row = (await c.execute(q)).first()
        return User(*row) if row else None

    async def tenant_name(self, tenant_id: str) -> str | None:
        """The workspace's own name, which the console shows in its header."""
        q = sa.select(tenants.c.name).where(tenants.c.id == tenant_id)
        async with self.db.tenant_tx(tenant_id) as c:
            return (await c.execute(q)).scalar()

    async def roles(self, tenant_id: str, user_id: str) -> dict[str, str]:
        """Team id to role for every active membership, in the order the memberships were made."""
        q = (
            sa.select(members.c.team_id, members.c.role)
            .join(teams, teams.c.id == members.c.team_id)
            # An archived team leaves the token (c-198).
            .where(members.c.user_id == user_id, members.c.status == "active", teams.c.status == "active")
            .order_by(members.c.created_at, members.c.id)
        )
        async with self.db.tenant_tx(tenant_id) as c:
            rows = (await c.execute(q)).all()
        return {str(row[0]): str(row[1]) for row in rows}

    async def acting_teams(self, tenant_id: str, user_id: str, *, now: str) -> list[str]:
        """The teams the person may act in: their memberships, then, for a workspace admin, every other active team
        (c-208). The token's `team_ids`, which every service picks `X-Team-Id` from."""
        mine = list(await self.roles(tenant_id, user_id))
        store = RoleStore(self.db)
        if not await store.workspace_admin(tenant_id, user_id, now=now):
            return mine
        return [*mine, *(t for t in await store.active_teams(tenant_id) if t not in mine)]

    async def permission_version(self, tenant_id: str) -> int:
        """The tenant's permission version, which every role, assignment or membership change raises."""
        async with self.db.tenant_tx(tenant_id) as c:
            return await version_in(c, tenant_id)

    async def access(self, tenant_id: str, user_id: str, *, now: str) -> dict[str, list[str]]:
        """Team id (or `*`) to the role ids of every assignment that applies to the person and has not expired: the
        token's `access` claim, which ops_access reads on every check."""
        held = await RoleStore(self.db).holdings(tenant_id, user_id)
        out: dict[str, list[str]] = {}
        for a in active(held.assignments, now):
            if a.role_id not in out.setdefault(a.team_id, []):
                out[a.team_id].append(a.role_id)
        return out

    async def open_session(
        self,
        user: User,
        *,
        session_id: str,
        auth_method: str,
        refresh_hash: str,
        expires_at: str,
        at: str,
        request_id: str,
        provider_id: str | None = None,
    ) -> None:
        async with self.db.tenant_tx(user.tenant_id) as c:
            await c.execute(
                sessions.insert().values(
                    id=session_id,
                    tenant_id=user.tenant_id,
                    user_id=user.id,
                    auth_method=auth_method,
                    provider_id=provider_id,
                    refresh_hash=refresh_hash,
                    expires_at=expires_at,
                    last_seen_at=at,
                    created_at=at,
                )
            )
            await record(
                c,
                tenant_id=user.tenant_id,
                team_id=None,
                actor=user.id,
                action="auth.sign_in",
                target_kind="session",
                target_id=session_id,
                request_id=request_id,
                detail={"authMethod": auth_method},
            )

    async def session(self, session_id: str) -> SessionRef | None:
        q = sa.text("SELECT tenant_id, user_id, id FROM platform_session(:s)")
        async with self.db.system_tx() as c:
            row = (await c.execute(q, {"s": session_id})).first()
        return SessionRef(*row) if row else None

    async def method(self, ref: SessionRef) -> SessionMethod | None:
        q = sa.select(sessions.c.auth_method, sessions.c.provider_id).where(sessions.c.id == ref.id)
        async with self.db.tenant_tx(ref.tenant_id) as c:
            row = (await c.execute(q)).first()
        return SessionMethod(str(row[0]), row[1]) if row else None

    async def rotate(self, ref: SessionRef, *, presented: str, replacement: str, at: str, request_id: str) -> bool:
        """Swap the refresh hash when `presented` is the current one and the session lives. Otherwise the token was
        rotated already, so someone holds a copy: the session is revoked and the reuse audited."""
        live = (
            sessions.c.id == ref.id,
            sessions.c.revoked_at.is_(None),
            sessions.c.expires_at > at,
        )
        async with self.db.tenant_tx(ref.tenant_id) as c:
            swapped = await c.execute(
                sessions.update()
                .where(*live, sessions.c.refresh_hash == presented)
                .values(refresh_hash=replacement, last_seen_at=at)
            )
            if swapped.rowcount == 1:
                return True
        async with self.db.tenant_tx(ref.tenant_id) as c:
            revoked = await c.execute(sessions.update().where(*live).values(revoked_at=at))
            if revoked.rowcount == 1:
                await record(
                    c,
                    tenant_id=ref.tenant_id,
                    team_id=None,
                    actor=ref.user_id,
                    action="auth.refresh_reuse",
                    target_kind="session",
                    target_id=ref.id,
                    request_id=request_id,
                    detail={},
                )
        return False

    async def touch(self, ref: SessionRef, *, at: str) -> bool:
        """Whether the session lives; a live one records `at` as last seen."""
        q = (
            sessions.update()
            .where(sessions.c.id == ref.id, sessions.c.revoked_at.is_(None), sessions.c.expires_at > at)
            .values(last_seen_at=at)
        )
        async with self.db.tenant_tx(ref.tenant_id) as c:
            return (await c.execute(q)).rowcount == 1

    async def sign_out(self, ref: SessionRef, *, at: str, request_id: str) -> None:
        async with self.db.tenant_tx(ref.tenant_id) as c:
            ended = await c.execute(
                sessions.update().where(sessions.c.id == ref.id, sessions.c.revoked_at.is_(None)).values(revoked_at=at)
            )
            if ended.rowcount == 1:
                await record(
                    c,
                    tenant_id=ref.tenant_id,
                    team_id=None,
                    actor=ref.user_id,
                    action="auth.sign_out",
                    target_kind="session",
                    target_id=ref.id,
                    request_id=request_id,
                    detail={},
                )

    async def step_up(self, ref: SessionRef, *, at: str, request_id: str, method: str) -> None:
        """Audits a re-authentication on a live session; the token itself is never stored."""
        async with self.db.tenant_tx(ref.tenant_id) as c:
            await record(
                c,
                tenant_id=ref.tenant_id,
                team_id=None,
                actor=ref.user_id,
                action="auth.step_up",
                target_kind="session",
                target_id=ref.id,
                request_id=request_id,
                detail={"authMethod": method},
            )

    async def key(self, key_id: str) -> Key | None:
        q = sa.text(
            "SELECT id, tenant_id, team_id, secret_hash, scopes, created_by, usable FROM platform_key(:k, :now)"
        )
        async with self.db.system_tx() as c:
            row = (await c.execute(q, {"k": key_id, "now": now_iso()})).first()
        return Key(row[0], row[1], row[2], row[3], list(row[4]), row[5], bool(row[6])) if row else None

    async def key_used(self, key: Key, *, at: str) -> dict[str, Any] | None:
        """Moves the key's last use and returns what it may start (c-246), None for a key with no target. Read here,
        under the tenant, so the pre-tenant lookup function keeps returning only what verifying needs."""
        k = api_keys
        async with self.db.tenant_tx(key.tenant_id) as c:
            await c.execute(k.update().where(k.c.id == key.id).values(last_used_at=at))
            row = (
                await c.execute(sa.select(k.c.target_kind, k.c.target_id, k.c.target_version).where(k.c.id == key.id))
            ).first()
        if row is None or not row[0]:
            return None
        return {"kind": str(row[0]), "id": str(row[1]), "version": row[2]}
