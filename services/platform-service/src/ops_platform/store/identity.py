"""Who a person or key is, and their sessions.

Lookups that find the tenant (a user by email, a session by id, a key by prefix) run in `system_tx`; everything after
runs in `tenant_tx` for that tenant. Refresh rotation is a compare-and-set on the stored hash, so two refreshes racing
on one token cannot both win. Sign-in, sign-out and a revocation for refresh-token reuse each write their audit entry
in the same transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import sqlalchemy as sa

from ops_service_kit.ids import now_iso
from ops_store import Guarantee

from .audit import record
from .tables import api_keys, members, sessions, users
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

    async def roles(self, tenant_id: str, user_id: str) -> dict[str, str]:
        """Team id to role for every active membership, in the order the memberships were made."""
        q = (
            sa.select(members.c.team_id, members.c.role)
            .where(members.c.user_id == user_id, members.c.status == "active")
            .order_by(members.c.created_at, members.c.id)
        )
        async with self.db.tenant_tx(tenant_id) as c:
            rows = (await c.execute(q)).all()
        return {str(row[0]): str(row[1]) for row in rows}

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
    ) -> None:
        async with self.db.tenant_tx(user.tenant_id) as c:
            await c.execute(
                sessions.insert().values(
                    id=session_id,
                    tenant_id=user.tenant_id,
                    user_id=user.id,
                    auth_method=auth_method,
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

    async def key(self, key_id: str) -> Key | None:
        q = sa.text(
            "SELECT id, tenant_id, team_id, secret_hash, scopes, created_by, usable FROM platform_key(:k, :now)"
        )
        async with self.db.system_tx() as c:
            row = (await c.execute(q, {"k": key_id, "now": now_iso()})).first()
        return Key(row[0], row[1], row[2], row[3], list(row[4]), row[5], bool(row[6])) if row else None

    async def key_used(self, key: Key, *, at: str) -> None:
        async with self.db.tenant_tx(key.tenant_id) as c:
            await c.execute(api_keys.update().where(api_keys.c.id == key.id).values(last_used_at=at))
