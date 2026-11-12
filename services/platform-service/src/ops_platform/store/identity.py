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

from ops_access import ANY_TEAM, OWNER, active, encode_grid
from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee

from .audit import record
from .roles import RoleStore, version_in
from .tables import api_keys, members, oauth_clients, role_assignments, sessions, teams, tenants, users
from .tenancy import KEY_LOOKUP, SESSION_LOOKUP, SIGNIN_LOOKUP, TenantDb


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
class Client:
    """An assistant that registered itself; `redirect_uris` are the only addresses a code may be sent to."""

    id: str
    name: str
    redirect_uris: list[str]
    consented_at: str | None
    tenant_id: str | None


@dataclass(frozen=True)
class Grant:
    """What an assistant was allowed: one person, one team, one address, for a client. `code_*` is the authorization
    code it was opened with."""

    id: str
    tenant_id: str
    user_id: str
    client_id: str
    team_id: str
    resource: str
    auth_method: str
    code_hash: str | None
    code_challenge: str | None
    redirect_uri: str | None
    code_expires_at: str | None
    code_used_at: str | None
    expires_at: str
    revoked_at: str | None
    created_at: str


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
        async with self.db.system_tx(SIGNIN_LOOKUP) as c:
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

    async def workspace_open_to(self, tenant_id: str, user_id: str) -> str:
        """`open` in an active workspace; in a closed one, `open` for its owner and `closed` for everyone else; `gone`
        once its purge has started."""
        async with self.db.tenant_tx(tenant_id) as c:
            status = (await c.execute(sa.select(tenants.c.status).where(tenants.c.id == tenant_id))).scalar()
            if status in {"active", "suspended"}:
                return "open"
            if status != "closed":
                return "gone"
            owner = (
                await c.execute(
                    sa.select(role_assignments.c.subject_id).where(
                        role_assignments.c.role_id == OWNER.id, role_assignments.c.team_id == ANY_TEAM
                    )
                )
            ).scalar()
        return "open" if owner == user_id else "closed"

    async def roles(self, tenant_id: str, user_id: str) -> dict[str, str]:
        """Team id to role for every active membership, in the order the memberships were made."""
        q = (
            sa.select(members.c.team_id, members.c.role)
            .join(teams, teams.c.id == members.c.team_id)
            # An archived team leaves the token.
            .where(members.c.user_id == user_id, members.c.status == "active", teams.c.status == "active")
            .order_by(members.c.created_at, members.c.id)
        )
        async with self.db.tenant_tx(tenant_id) as c:
            rows = (await c.execute(q)).all()
        return {str(row[0]): str(row[1]) for row in rows}

    async def acting_teams(self, tenant_id: str, user_id: str, *, now: str) -> list[str]:
        """The teams the person may act in: their memberships, then, for a workspace admin, every other active team. The
        token's `team_ids`, which every service picks `X-Team-Id` from."""
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

    async def grids(
        self, tenant_id: str, role_ids: list[str], *, stored_only: bool = False
    ) -> dict[str, dict[str, str]]:
        """Each role's cells as stored now, encoded for the token's `grids` claim, which every service decides from. A
        role with no stored row holds no cell, or with `stored_only` is left out so a reader falls back to its seed."""
        found = await RoleStore(self.db).grids(tenant_id, role_ids) if role_ids else {}
        return {r: encode_grid(found.get(r, [])) for r in role_ids if r in found or not stored_only}

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
        async with self.db.system_tx(SESSION_LOOKUP) as c:
            row = (await c.execute(q, {"s": session_id})).first()
        return SessionRef(*row) if row else None

    async def method(self, ref: SessionRef) -> SessionMethod | None:
        q = sa.select(sessions.c.auth_method, sessions.c.provider_id).where(sessions.c.id == ref.id)
        async with self.db.tenant_tx(ref.tenant_id) as c:
            row = (await c.execute(q)).first()
        return SessionMethod(str(row[0]), row[1]) if row else None

    async def rotate(
        self,
        ref: SessionRef,
        *,
        presented: str,
        replacement: str,
        at: str,
        request_id: str,
        kind: str = "console",
        team_id: str | None = None,
    ) -> bool:
        """Swap the refresh hash when `presented` is the current one and the session lives. Otherwise the token was
        rotated already, so someone holds a copy: the session is revoked and the reuse audited. `kind` keeps a
        console token and an assistant's from renewing each other: a session of the other kind is left alone."""
        live = (
            sessions.c.id == ref.id,
            sessions.c.kind == kind,
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
                    team_id=team_id,
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
        async with self.db.system_tx(KEY_LOOKUP) as c:
            row = (await c.execute(q, {"k": key_id, "now": now_iso()})).first()
        return Key(row[0], row[1], row[2], row[3], list(row[4]), row[5], bool(row[6])) if row else None

    async def key_used(self, key: Key, *, at: str) -> dict[str, Any] | None:
        """Moves the key's last use and returns what it may start, None for a key with no target. Read here,
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

    # ── Assistants at a team's MCP address: registered clients and the grants a person gives them ──

    async def team_tenant(self, team_id: str) -> tuple[str, str] | None:
        """The tenant of an active team, found before anyone is signed in so the address of an authorize request can
        be checked; None for a team that does not exist or is archived."""
        q = sa.text("SELECT tenant_id, status FROM platform_team(:t)")
        async with self.db.system_tx(SIGNIN_LOOKUP) as c:
            row = (await c.execute(q, {"t": team_id})).first()
        return (str(row[0]), str(row[1])) if row and row[1] == "active" else None

    async def team_name(self, tenant_id: str, team_id: str) -> str | None:
        async with self.db.tenant_tx(tenant_id) as c:
            return (await c.execute(sa.select(teams.c.name).where(teams.c.id == team_id))).scalar()

    async def register_client(self, client: Client, *, at: str, stale_before: str) -> None:
        """Adds a client after deleting the ones never consented to that were registered before `stale_before`."""
        t = oauth_clients
        async with self.db.system_tx(SIGNIN_LOOKUP) as c:
            await c.execute(t.delete().where(t.c.consented_at.is_(None), t.c.created_at < stale_before))
            await c.execute(
                t.insert().values(id=client.id, name=client.name, redirect_uris=client.redirect_uris, created_at=at)
            )

    async def client(self, client_id: str) -> Client | None:
        t = oauth_clients
        async with self.db.system_tx(SIGNIN_LOOKUP) as c:
            row = (await c.execute(sa.select(t).where(t.c.id == client_id))).mappings().first()
        if row is None:
            return None
        return Client(row["id"], row["name"], list(row["redirect_uris"]), row["consented_at"], row["tenant_id"])

    async def clients_of_tenant(self, tenant_id: str) -> int:
        t = oauth_clients
        async with self.db.system_tx(SIGNIN_LOOKUP) as c:
            return int((await c.execute(sa.select(sa.func.count()).where(t.c.tenant_id == tenant_id))).scalar_one())

    async def open_grant(
        self,
        user: User,
        *,
        client: Client,
        session_id: str,
        auth_method: str,
        team_id: str,
        resource: str,
        code_hash: str,
        code_challenge: str,
        redirect_uri: str,
        code_expires_at: str,
        expires_at: str,
        at: str,
        request_id: str,
    ) -> None:
        """The grant a person gave by pressing Allow: a session of kind `mcp`, waiting for its code to be exchanged.
        The first Allow of a client adds its tenant and writes the registration to this tenant's audit log."""
        async with self.db.tenant_tx(user.tenant_id) as c:
            await c.execute(
                sessions.insert().values(
                    id=session_id,
                    tenant_id=user.tenant_id,
                    user_id=user.id,
                    auth_method=auth_method,
                    # Replaced by the real refresh hash when the code is exchanged; nobody holds this one.
                    refresh_hash=f"pending-{session_id}",
                    expires_at=expires_at,
                    last_seen_at=at,
                    created_at=at,
                    kind="mcp",
                    client_id=client.id,
                    team_id=team_id,
                    resource=resource,
                    code_hash=code_hash,
                    code_challenge=code_challenge,
                    redirect_uri=redirect_uri,
                    code_expires_at=code_expires_at,
                )
            )
            if client.consented_at is None:
                await record(
                    c,
                    tenant_id=user.tenant_id,
                    team_id=team_id,
                    actor=user.id,
                    action="oauth.client_registered",
                    target_kind="oauth_client",
                    target_id=client.id,
                    request_id=request_id,
                    detail={"name": client.name},
                )
            await record(
                c,
                tenant_id=user.tenant_id,
                team_id=team_id,
                actor=user.id,
                action="oauth.grant_allowed",
                target_kind="session",
                target_id=session_id,
                request_id=request_id,
                detail={"clientId": client.id, "resource": resource},
            )
        t = oauth_clients
        async with self.db.system_tx(SIGNIN_LOOKUP) as c:
            await c.execute(
                t.update()
                .where(t.c.id == client.id, t.c.consented_at.is_(None))
                .values(consented_at=at, tenant_id=user.tenant_id)
            )

    async def grant(self, ref: SessionRef) -> Grant | None:
        """The MCP grant behind a session id; None for a console session."""
        s = sessions
        q = sa.select(s).where(s.c.id == ref.id, s.c.kind == "mcp")
        async with self.db.tenant_tx(ref.tenant_id) as c:
            row = (await c.execute(q)).mappings().first()
        if row is None:
            return None
        return Grant(
            row["id"], row["tenant_id"], row["user_id"], row["client_id"], row["team_id"], row["resource"],
            row["auth_method"], row["code_hash"], row["code_challenge"], row["redirect_uri"],
            row["code_expires_at"], row["code_used_at"], row["expires_at"], row["revoked_at"], row["created_at"],
        )  # fmt: skip

    async def redeem_code(self, grant: Grant, *, code_hash: str, refresh_hash: str, at: str) -> bool:
        """Marks the grant's code used and holds the first refresh hash, once. A second use of a code that was used
        ends the grant it opened (someone holds a copy)."""
        s = sessions
        live = (s.c.id == grant.id, s.c.kind == "mcp", s.c.code_hash == code_hash, s.c.revoked_at.is_(None))
        async with self.db.tenant_tx(grant.tenant_id) as c:
            won = await c.execute(
                s.update()
                .where(*live, s.c.code_used_at.is_(None), s.c.code_expires_at > at, s.c.expires_at > at)
                .values(code_used_at=at, refresh_hash=refresh_hash, last_seen_at=at)
            )
            if won.rowcount == 1:
                return True
        if grant.code_used_at is not None:
            await self.end_grant(grant, at=at, by="replay", actor=grant.user_id, request_id="")
        return False

    async def end_grant(self, grant: Grant, *, at: str, by: str, actor: str, request_id: str) -> bool:
        """Ends the connection once and audits it with who ended it: `person`, `admin` (the person left the team or lost
        the right to run tools), or `replay` (a code used twice)."""
        s = sessions
        async with self.db.tenant_tx(grant.tenant_id) as c:
            ended = await c.execute(
                s.update().where(s.c.id == grant.id, s.c.kind == "mcp", s.c.revoked_at.is_(None)).values(revoked_at=at)
            )
            if ended.rowcount != 1:
                return False
            await record(
                c,
                tenant_id=grant.tenant_id,
                team_id=grant.team_id,
                actor=actor,
                action="oauth.grant_ended",
                target_kind="session",
                target_id=grant.id,
                request_id=request_id or new_request(),
                detail={"by": by, "clientId": grant.client_id},
            )
        return True

    async def grants_of(self, tenant_id: str, user_id: str, *, now: str) -> list[dict[str, Any]]:
        """A person's live connections, newest first, with the client's name and the team's."""
        s, t, k = sessions, teams, oauth_clients
        q = (
            sa.select(s.c.id, s.c.client_id, s.c.team_id, s.c.resource, s.c.created_at, s.c.expires_at, t.c.name)
            .join(t, sa.and_(t.c.id == s.c.team_id, t.c.tenant_id == s.c.tenant_id))
            .where(
                s.c.user_id == user_id,
                s.c.kind == "mcp",
                s.c.code_used_at.is_not(None),
                s.c.revoked_at.is_(None),
                s.c.expires_at > now,
            )
            .order_by(s.c.created_at.desc())
        )
        async with self.db.tenant_tx(tenant_id) as c:
            rows = (await c.execute(q)).all()
        names: dict[str, str] = {}
        async with self.db.system_tx(SIGNIN_LOOKUP) as c:
            found = (await c.execute(sa.select(k.c.id, k.c.name).where(k.c.id.in_({r[1] for r in rows})))).all()
            names = {str(r[0]): str(r[1]) for r in found}
        return [
            {
                "id": r[0], "clientId": r[1], "clientName": names.get(str(r[1]), str(r[1])), "teamId": r[2],
                "teamName": r[6], "resource": r[3], "createdAt": r[4], "expiresAt": r[5],
            }
            for r in rows
        ]  # fmt: skip


def new_request() -> str:
    return new_id("req")
