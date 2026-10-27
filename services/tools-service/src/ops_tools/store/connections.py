"""Connections at rest: how the platform signs in to one system, per environment, with the tokens a sign-in holds.

A connection and its environments are one aggregate written against its `revision` (409 on a stale write), as a module
is. Secret parts are never here: an environment names the `tool_secrets` row holding each one (`secrets`), so there is
one secret store and one cipher path. Tokens and a sign-in's PKCE verifier are ciphertext only.

`connection_tokens` is keyed (tenant, connection, environment, person); `person_id` is `''` for a shared token, a NOT
NULL scope column under a plain primary key, so the key dedupes on every database. A refreshed token is stored only
against the rotation it replaced (CAS), with no lock held while the token request is in flight; a caller that loses
reads the winner's token.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_store import Guarantee
from ops_store.search import contains
from ops_store.team_scope import team_visible

from .modules import metadata, tool_modules

_TS = sa.DateTime(timezone=True)
SHARED = ""

connections = sa.Table(
    "connections",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    # The team that owns it; `available_to` lists the other teams whose modules may use it (null: none).
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("name", sa.String(200), nullable=False),
    # A kind in ops_tools.auth.kinds (none, api_key, basic, bearer, oauth2_client_credentials, oauth2_auth_code).
    sa.Column("auth_kind", sa.String(40), nullable=False),
    sa.Column("available_to", sa.JSON),
    # draft, healthy, needs_reconnect, revoked or error; `status_detail` says what the system refused, never a value.
    sa.Column("status", sa.String(24), nullable=False),
    sa.Column("status_detail", sa.Text),
    # When the consent an older integration record carries runs out (the dev seed's); null for none.
    sa.Column("expires_at", _TS),
    sa.Column("catalog_id", sa.String(64)),
    sa.Column("revision", sa.Integer, nullable=False),
    sa.Column("created_by", sa.String(200), nullable=False),
    sa.Column("created_at", _TS, nullable=False),
    sa.Column("updated_by", sa.String(200), nullable=False),
    sa.Column("updated_at", _TS, nullable=False),
    sa.Index("ix_connections_team", "tenant_id", "team_id"),
)

connection_environments = sa.Table(
    "connection_environments",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("connection_id", sa.String(64), primary_key=True),
    # test or production.
    sa.Column("environment", sa.String(16), primary_key=True),
    # The kind's plain settings (header name, username, token address, client id, scopes, a client certificate's PEM).
    sa.Column("settings", sa.JSON, nullable=False),
    # Each secret field to the tool_secrets name holding its value.
    sa.Column("secrets", sa.JSON, nullable=False),
    sa.Column("updated_by", sa.String(200), nullable=False),
    sa.Column("updated_at", _TS, nullable=False),
    sa.ForeignKeyConstraint(
        ["tenant_id", "connection_id"], ["connections.tenant_id", "connections.id"], ondelete="CASCADE"
    ),
)

connection_tokens = sa.Table(
    "connection_tokens",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("connection_id", sa.String(64), primary_key=True),
    sa.Column("environment", sa.String(16), primary_key=True),
    # '' for the connection's shared token; a person's id once each person signs in (slice 14).
    sa.Column("person_id", sa.String(200), primary_key=True),
    sa.Column("access_ct", sa.Text, nullable=False),
    sa.Column("refresh_ct", sa.Text),
    sa.Column("expires_at", _TS),
    sa.Column("scopes", sa.JSON, nullable=False),
    # Who the system says signed in, when it says (an id token's or userinfo's subject).
    sa.Column("account", sa.String(320)),
    # Rises on every refresh; a reader can tell which token a call used.
    sa.Column("rotations", sa.Integer, nullable=False),
    sa.Column("refreshed_at", _TS, nullable=False),
    sa.ForeignKeyConstraint(
        ["tenant_id", "connection_id"], ["connections.tenant_id", "connections.id"], ondelete="CASCADE"
    ),
)

oauth_states = sa.Table(
    "oauth_states",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    # sha256 of the state sent to the system; the state itself is never stored.
    sa.Column("state_hash", sa.String(64), primary_key=True),
    sa.Column("connection_id", sa.String(64), nullable=False),
    sa.Column("environment", sa.String(16), nullable=False),
    # The person who started the sign-in; only they finish it.
    sa.Column("person_id", sa.String(200), nullable=False),
    sa.Column("verifier_ct", sa.Text, nullable=False),
    sa.Column("redirect_uri", sa.Text, nullable=False),
    sa.Column("expires_at", _TS, nullable=False),
    # Set in the transaction that exchanges the code: a state is used once.
    sa.Column("used_at", _TS),
)

connection_audit = sa.Table(
    "connection_audit",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("connection_id", sa.String(64), nullable=False),
    # created, changed, secret_set, signed_in, signed_out, refresh_failed, deleted.
    sa.Column("action", sa.String(32), nullable=False),
    sa.Column("environment", sa.String(16)),
    sa.Column("actor", sa.String(200), nullable=False),
    sa.Column("at", _TS, nullable=False),
    # Names only (which fields changed, which account signed in); never a value or a token.
    sa.Column("detail", sa.JSON, nullable=False),
    sa.Index("ix_connection_audit_connection", "tenant_id", "connection_id"),
)


class StaleConnection(RuntimeError):
    """The connection changed since it was read; nothing was written."""


class ConnectionInUse(RuntimeError):
    def __init__(self, modules: list[str]) -> None:
        super().__init__(", ".join(modules))
        self.modules = modules


Row = dict[str, Any]


class ConnectionStore:
    # A change, its environments and its audit row land together (TRANSACTION) against the revision read (CAS); a
    # token is stored against the rotation it replaced (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.CAS})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    # ── Records ───────────────────────────────────────────────────────────

    async def _environments(self, c: AsyncConnection, tenant_id: str, ids: list[str]) -> dict[str, dict[str, Row]]:
        if not ids:
            return {}
        q = connection_environments.select().where(
            connection_environments.c.tenant_id == tenant_id, connection_environments.c.connection_id.in_(ids)
        )
        out: dict[str, dict[str, Row]] = {}
        for r in (await c.execute(q)).mappings():
            out.setdefault(str(r["connection_id"]), {})[str(r["environment"])] = dict(r)
        return out

    async def _used_by(self, c: AsyncConnection, tenant_id: str, ids: list[str]) -> dict[str, list[Row]]:
        """The modules pointing at each connection, joined here so a list never looks them up one by one."""
        if not ids:
            return {}
        q = sa.select(tool_modules.c.connection_id, tool_modules.c.id, tool_modules.c.display_name).where(
            tool_modules.c.tenant_id == tenant_id, tool_modules.c.connection_id.in_(ids), team_visible(tool_modules)
        )
        out: dict[str, list[Row]] = {}
        for r in await c.execute(q.order_by(tool_modules.c.display_name)):
            out.setdefault(str(r.connection_id), []).append({"id": r.id, "name": r.display_name})
        return out

    async def _whole(self, c: AsyncConnection, tenant_id: str, rows: list[Row]) -> list[Row]:
        ids = [str(r["id"]) for r in rows]
        envs = await self._environments(c, tenant_id, ids)
        used = await self._used_by(c, tenant_id, ids)
        return [{**r, "environments": envs.get(str(r["id"]), {}), "used_by": used.get(str(r["id"]), [])} for r in rows]

    async def get(self, tenant_id: str, connection_id: str) -> Row | None:
        q = connections.select().where(connections.c.tenant_id == tenant_id, connections.c.id == connection_id)
        async with self.engine.connect() as c:
            row = (await c.execute(q)).mappings().first()
            return (await self._whole(c, tenant_id, [dict(row)]))[0] if row else None

    async def by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, Row]:
        """The named connections without their environments: what a module list shows of each."""
        if not ids:
            return {}
        q = connections.select().where(connections.c.tenant_id == tenant_id, connections.c.id.in_(ids))
        async with self.engine.connect() as c:
            return {str(r["id"]): dict(r) for r in (await c.execute(q)).mappings()}

    @staticmethod
    def _visible(tenant_id: str, teams: list[str], search: str) -> sa.ColumnElement[bool]:
        """`teams`: the owning teams the caller sees (its own, c-509)."""
        where = sa.and_(connections.c.tenant_id == tenant_id, contains(connections.c.name, search))
        return sa.and_(where, connections.c.team_id.in_(teams))

    async def count(self, tenant_id: str, teams: list[str], search: str) -> int:
        q = sa.select(sa.func.count()).select_from(connections).where(self._visible(tenant_id, teams, search))
        async with self.engine.connect() as c:
            return int((await c.execute(q)).scalar_one())

    async def page(self, tenant_id: str, teams: list[str], search: str, offset: int, limit: int) -> list[Row]:
        q = (
            connections.select()
            .where(self._visible(tenant_id, teams, search))
            .order_by(sa.func.lower(connections.c.name), connections.c.id)
            .offset(offset)
            .limit(limit)
        )
        async with self.engine.connect() as c:
            rows = [dict(r) for r in (await c.execute(q)).mappings()]
            return await self._whole(c, tenant_id, rows)

    async def create(self, row: Row, *, actor: str, at: datetime) -> bool:
        """False when the id is taken (nothing written)."""
        async with self.engine.begin() as c:
            try:
                async with c.begin_nested():
                    await c.execute(connections.insert().values(**row))
            except IntegrityError:
                return False
            event = {"action": "created", "actor": actor, "at": at, "detail": {"kind": row["auth_kind"]}}
            await self._audit(c, row["tenant_id"], row["id"], event)
        return True

    async def change(
        self,
        tenant_id: str,
        connection_id: str,
        expected_revision: int,
        values: Row,
        *,
        actor: str,
        at: datetime,
        environment: tuple[str, Row, Row] | None = None,
        action: str = "changed",
        detail: Row | None = None,
    ) -> None:
        """Writes `values` (and one environment's settings and secret names) only against the revision read, with its
        audit row; StaleConnection otherwise."""
        async with self.engine.begin() as c:
            q = (
                connections.update()
                .where(
                    connections.c.tenant_id == tenant_id,
                    connections.c.id == connection_id,
                    connections.c.revision == expected_revision,
                )
                .values(**values, revision=expected_revision + 1, updated_by=actor, updated_at=at)
            )
            if (await c.execute(q)).rowcount != 1:
                raise StaleConnection(connection_id)
            env_name = None
            if environment is not None:
                env_name, settings, secrets = environment
                key = (
                    connection_environments.c.tenant_id == tenant_id,
                    connection_environments.c.connection_id == connection_id,
                    connection_environments.c.environment == env_name,
                )
                fields = {"settings": settings, "secrets": secrets, "updated_by": actor, "updated_at": at}
                if (await c.execute(connection_environments.update().where(*key).values(**fields))).rowcount == 0:
                    await c.execute(
                        connection_environments.insert().values(
                            tenant_id=tenant_id, connection_id=connection_id, environment=env_name, **fields
                        )
                    )
            event = {"action": action, "environment": env_name, "actor": actor, "at": at, "detail": detail or {}}
            await self._audit(c, tenant_id, connection_id, event)

    async def delete(self, tenant_id: str, connection_id: str, *, actor: str, at: datetime) -> bool:
        """False when there is no such connection; ConnectionInUse naming the modules that use it, checked in the
        delete's own transaction."""
        async with self.engine.begin() as c:
            used = (await self._used_by(c, tenant_id, [connection_id])).get(connection_id, [])
            if used:
                raise ConnectionInUse([str(u["name"]) for u in used])
            q = connections.delete().where(connections.c.tenant_id == tenant_id, connections.c.id == connection_id)
            if (await c.execute(q)).rowcount == 0:
                return False
            await self._audit(c, tenant_id, connection_id, {"action": "deleted", "actor": actor, "at": at})
        return True

    async def _audit(self, c: AsyncConnection, tenant_id: str, connection_id: str, event: Row) -> None:
        """`event`: action, environment, actor, at and detail (names only)."""
        await c.execute(
            connection_audit.insert().values(
                tenant_id=tenant_id, connection_id=connection_id, **{"environment": None, "detail": {}, **event}
            )
        )

    async def audit(self, tenant_id: str, connection_id: str, *, limit: int = 50) -> list[Row]:
        q = (
            connection_audit.select()
            .where(connection_audit.c.tenant_id == tenant_id, connection_audit.c.connection_id == connection_id)
            .order_by(connection_audit.c.id.desc())
            .limit(limit)
        )
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def note(self, tenant_id: str, connection_id: str, event: Row) -> None:
        """An audit row on its own (a sign-in, a sign-out, a failed refresh): action, environment, actor, at, detail."""
        async with self.engine.begin() as c:
            await self._audit(c, tenant_id, connection_id, event)

    async def set_status(self, tenant_id: str, connection_id: str, status: str, detail: str | None) -> None:
        """The gateway's own finding (a refused token request); not a person's edit, so the revision stays."""
        q = (
            connections.update()
            .where(connections.c.tenant_id == tenant_id, connections.c.id == connection_id)
            .values(status=status, status_detail=detail)
        )
        async with self.engine.begin() as c:
            await c.execute(q)

    # ── Tokens ────────────────────────────────────────────────────────────

    @staticmethod
    def _token_key(tenant_id: str, connection_id: str, environment: str, person: str) -> tuple[Any, ...]:
        t = connection_tokens.c
        return (
            t.tenant_id == tenant_id,
            t.connection_id == connection_id,
            t.environment == environment,
            t.person_id == person,
        )

    async def token(self, tenant_id: str, connection_id: str, environment: str, person: str = SHARED) -> Row | None:
        q = connection_tokens.select().where(*self._token_key(tenant_id, connection_id, environment, person))
        async with self.engine.connect() as c:
            row = (await c.execute(q)).mappings().first()
            return dict(row) if row else None

    async def tokens(self, tenant_id: str, connection_id: str) -> list[Row]:
        q = connection_tokens.select().where(
            connection_tokens.c.tenant_id == tenant_id, connection_tokens.c.connection_id == connection_id
        )
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def put_token(
        self,
        tenant_id: str,
        connection_id: str,
        environment: str,
        values: Row,
        *,
        expected_rotations: int | None,
        person: str = SHARED,
    ) -> bool:
        """Stores a token only if the row is still as it was read: `expected_rotations` None means there was no row (an
        insert, which fails if another caller inserted first), else the rotation read (CAS). False when another caller
        stored first; nothing is written then. No lock is held while the token is fetched."""
        key = self._token_key(tenant_id, connection_id, environment, person)
        async with self.engine.begin() as c:
            if expected_rotations is not None:
                q = connection_tokens.update().where(*key, connection_tokens.c.rotations == expected_rotations)
                return (await c.execute(q.values(**values))).rowcount == 1
            try:
                async with c.begin_nested():
                    await c.execute(
                        connection_tokens.insert().values(
                            tenant_id=tenant_id,
                            connection_id=connection_id,
                            environment=environment,
                            person_id=person,
                            **values,
                        )
                    )
            except IntegrityError:
                return False
            return True

    async def replace_token(
        self, tenant_id: str, connection_id: str, environment: str, values: Row, person: str = SHARED
    ) -> None:
        """A finished sign-in's token, whatever was held before."""
        key = self._token_key(tenant_id, connection_id, environment, person)
        async with self.engine.begin() as c:
            if (await c.execute(connection_tokens.update().where(*key).values(**values))).rowcount == 0:
                await c.execute(
                    connection_tokens.insert().values(
                        tenant_id=tenant_id,
                        connection_id=connection_id,
                        environment=environment,
                        person_id=person,
                        **values,
                    )
                )

    async def forget_token(self, tenant_id: str, connection_id: str, environment: str, person: str = SHARED) -> bool:
        q = connection_tokens.delete().where(*self._token_key(tenant_id, connection_id, environment, person))
        async with self.engine.begin() as c:
            return (await c.execute(q)).rowcount > 0

    # ── Sign-in states ────────────────────────────────────────────────────

    async def add_state(self, row: Row, *, now: datetime) -> None:
        """Stores a sign-in in progress; expired ones of the tenant go in the same transaction, so the table holds only
        sign-ins under ten minutes old and the used ones not yet pruned."""
        async with self.engine.begin() as c:
            await c.execute(
                oauth_states.delete().where(
                    oauth_states.c.tenant_id == row["tenant_id"], oauth_states.c.expires_at < now
                )
            )
            await c.execute(oauth_states.insert().values(**row))

    async def take_state(
        self, tenant_id: str, state_hash: str, *, connection_id: str, person: str, now: datetime
    ) -> Row | None:
        """The sign-in under this state, marked used in the same statement that checks it is this person's, for this
        connection, unused and unexpired; None otherwise, so another person's attempt never spends it."""
        s = oauth_states.c
        where = (
            s.tenant_id == tenant_id,
            s.state_hash == state_hash,
            s.connection_id == connection_id,
            s.person_id == person,
            s.used_at.is_(None),
            s.expires_at >= now,
        )
        async with self.engine.begin() as c:
            row = (await c.execute(oauth_states.select().where(*where))).mappings().first()
            if row is None:
                return None
            if (await c.execute(oauth_states.update().where(*where).values(used_at=now))).rowcount != 1:
                return None
            return dict(row)
