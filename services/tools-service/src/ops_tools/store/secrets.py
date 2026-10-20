"""Tool secrets at rest: only ciphertext (`ops_policy.cipher`), never a value, and an audit row for every create,
rotate, delete and use, written in the same transaction as the change it records."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_store import Guarantee
from ops_store.search import contains

from .modules import metadata

_TS = sa.DateTime(timezone=True)

tool_secrets = sa.Table(
    "tool_secrets",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    # ^[A-Z][A-Z0-9_]*$, the name a `{{NAME}}` reference uses.
    sa.Column("name", sa.String(120), primary_key=True),
    sa.Column("ciphertext", sa.Text, nullable=False),
    # Rises on every rotation, so a reader can tell which value a call used.
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("created_by", sa.String(200), nullable=False),
    sa.Column("created_at", _TS, nullable=False),
    sa.Column("rotated_at", _TS),
    sa.Column("last_used_at", _TS),
    # The teams whose tool modules may read it; null is every team (c-093).
    sa.Column("teams", sa.JSON),
    # The template slot a provisioned record fills, found again by it on the next run, and what a person may change:
    # `system` nothing, `managed` anything (c-180). Null on a record no template made.
    sa.Column("template_id", sa.String(120), index=True),
    sa.Column("protection", sa.String(16)),
    # The connection whose secret part this is (c-330); written through the connection, listed as belonging to it,
    # never rotated or deleted on its own. Null for a secret a person added on the Secrets page.
    sa.Column("connection_id", sa.String(64)),
)

secret_audit = sa.Table(
    "secret_audit",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, index=True),
    sa.Column("name", sa.String(120), nullable=False),
    sa.Column("action", sa.String(16), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("actor", sa.String(200), nullable=False),
    # For a use: the tool whose call sent the value.
    sa.Column("tool", sa.String(120)),
    sa.Column("at", _TS, nullable=False),
)


class SecretStore:
    # A change and its audit row land together (TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def _audit(self, c: AsyncConnection, tenant_id: str, change: dict[str, Any]) -> None:
        await c.execute(secret_audit.insert().values(tenant_id=tenant_id, **change))

    async def listed(self, tenant_id: str) -> list[dict[str, Any]]:
        """Every secret's metadata; the ciphertext is not selected."""
        cols = [c for c in tool_secrets.c if c.name != "ciphertext"]
        q = sa.select(*cols).where(tool_secrets.c.tenant_id == tenant_id).order_by(tool_secrets.c.name)
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def page(
        self, tenant_id: str, search: str, offset: int, limit: int, template_id: str | None = None
    ) -> list[dict[str, Any]]:
        """One page of the secrets whose name contains `search`, by name; the ciphertext is not selected, and LIMIT and
        OFFSET run in the query."""
        cols = [c for c in tool_secrets.c if c.name != "ciphertext"]
        q = (
            sa.select(*cols)
            .where(self._matching(tenant_id, search, template_id))
            .order_by(sa.func.lower(tool_secrets.c.name))
        )
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q.offset(offset).limit(limit))).mappings()]

    async def count(self, tenant_id: str, search: str, template_id: str | None = None) -> int:
        q = sa.select(sa.func.count()).select_from(tool_secrets).where(self._matching(tenant_id, search, template_id))
        async with self.engine.connect() as c:
            return int((await c.execute(q)).scalar_one())

    @staticmethod
    def _matching(tenant_id: str, search: str, template_id: str | None = None) -> sa.ColumnElement[bool]:
        named = sa.and_(tool_secrets.c.tenant_id == tenant_id, contains(tool_secrets.c.name, search))
        return named if template_id is None else sa.and_(named, tool_secrets.c.template_id == template_id)

    async def create(
        self,
        tenant_id: str,
        name: str,
        ciphertext: str,
        *,
        actor: str,
        at: datetime,
        teams: list[str] | None = None,
        template: dict[str, str] | None = None,
        connection_id: str | None = None,
    ) -> bool:
        """False when the name is taken (nothing written). `template` carries the provisioner's `template_id` and
        `protection` (c-180); `connection_id` marks a connection's secret part (c-330)."""
        row = {"tenant_id": tenant_id, "name": name, "ciphertext": ciphertext, "version": 1, "teams": teams}
        if connection_id is not None:
            row["connection_id"] = connection_id
        row |= template or {}
        async with self.engine.begin() as c:
            try:
                async with c.begin_nested():
                    await c.execute(tool_secrets.insert().values(**row, created_by=actor, created_at=at))
            except IntegrityError:
                return False
            await self._audit(c, tenant_id, {"name": name, "action": "created", "version": 1, "actor": actor, "at": at})
        return True

    async def rotate(self, tenant_id: str, name: str, ciphertext: str, *, actor: str, at: datetime) -> int | None:
        """The new version, or None when there is no such secret."""
        async with self.engine.begin() as c:
            q = (
                tool_secrets.update()
                .where(tool_secrets.c.tenant_id == tenant_id, tool_secrets.c.name == name)
                .values(ciphertext=ciphertext, version=tool_secrets.c.version + 1, rotated_at=at)
                .returning(tool_secrets.c.version)
            )
            version = (await c.execute(q)).scalar()
            if version is None:
                return None
            await self._audit(
                c, tenant_id, {"name": name, "action": "rotated", "version": version, "actor": actor, "at": at}
            )
            return int(version)

    async def set_teams(self, tenant_id: str, name: str, teams: list[str] | None, *, actor: str, at: datetime) -> bool:
        """False when there is no such secret."""
        async with self.engine.begin() as c:
            mine = (tool_secrets.c.tenant_id == tenant_id, tool_secrets.c.name == name)
            # Update then read, not RETURNING: the store stays portable to databases without it (check_portable_store).
            if (await c.execute(tool_secrets.update().where(*mine).values(teams=teams))).rowcount == 0:
                return False
            version = (await c.execute(sa.select(tool_secrets.c.version).where(*mine))).scalar_one()
            await self._audit(
                c, tenant_id, {"name": name, "action": "scoped", "version": version, "actor": actor, "at": at}
            )
            return True

    async def delete(self, tenant_id: str, name: str, *, actor: str, at: datetime) -> bool:
        async with self.engine.begin() as c:
            q = (
                tool_secrets.delete()
                .where(tool_secrets.c.tenant_id == tenant_id, tool_secrets.c.name == name)
                .returning(tool_secrets.c.version)
            )
            version = (await c.execute(q)).scalar()
            if version is None:
                return False
            await self._audit(
                c, tenant_id, {"name": name, "action": "deleted", "version": version, "actor": actor, "at": at}
            )
            return True

    async def use(
        self, tenant_id: str, names: list[str], *, actor: str, tool: str, at: datetime, team: str | None = None
    ) -> tuple[dict[str, tuple[str, int]], list[str]]:
        """The ciphertext and version of each named secret that exists and `team`'s modules may read, recording the use
        of each in one transaction, and the names whose team scope leaves `team` out (not read, not recorded). Read on
        every call, never cached, so a rotation or a scope change applies to the next call."""
        if not names:
            return {}, []
        async with self.engine.begin() as c:
            q = sa.select(
                tool_secrets.c.name, tool_secrets.c.ciphertext, tool_secrets.c.version, tool_secrets.c.teams
            ).where(tool_secrets.c.tenant_id == tenant_id, tool_secrets.c.name.in_(names))
            rows = list(await c.execute(q))
            refused = sorted(r.name for r in rows if r.teams and team not in r.teams)
            found = {r.name: (r.ciphertext, int(r.version)) for r in rows if r.name not in refused}
            if found:
                await c.execute(
                    tool_secrets.update()
                    .where(tool_secrets.c.tenant_id == tenant_id, tool_secrets.c.name.in_(list(found)))
                    .values(last_used_at=at)
                )
            for name, (_, version) in found.items():
                change = {"name": name, "action": "used", "version": version, "actor": actor, "tool": tool, "at": at}
                await self._audit(c, tenant_id, change)
        return found, refused

    async def audit(self, tenant_id: str) -> list[dict[str, Any]]:
        q = secret_audit.select().where(secret_audit.c.tenant_id == tenant_id).order_by(secret_audit.c.id)
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]
