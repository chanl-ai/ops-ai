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
    # The team whose tool modules and connections read it (c-509): two teams that call the same system each hold their
    # own row under the same name, so a module installed in both resolves `{{NAME}}` to its own team's value.
    sa.Column("team_id", sa.String(64), primary_key=True),
    # ^[A-Z][A-Z0-9_]*$, the name a `{{NAME}}` reference uses.
    sa.Column("name", sa.String(120), primary_key=True),
    sa.Column("ciphertext", sa.Text, nullable=False),
    # Rises on every rotation, so a reader can tell which value a call used.
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("created_by", sa.String(200), nullable=False),
    sa.Column("created_at", _TS, nullable=False),
    sa.Column("rotated_at", _TS),
    sa.Column("last_used_at", _TS),
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
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("name", sa.String(120), nullable=False),
    sa.Column("action", sa.String(16), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("actor", sa.String(200), nullable=False),
    # For a use: the tool whose call sent the value.
    sa.Column("tool", sa.String(120)),
    sa.Column("at", _TS, nullable=False),
)


def _of(tenant_id: str, team_id: str) -> sa.ColumnElement[bool]:
    return sa.and_(tool_secrets.c.tenant_id == tenant_id, tool_secrets.c.team_id == team_id)


class SecretStore:
    """Every read and write names one team (`team_id`): no method reads or changes another team's rows."""

    # A change and its audit row land together (TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def _audit(self, c: AsyncConnection, tenant_id: str, team_id: str, change: dict[str, Any]) -> None:
        await c.execute(secret_audit.insert().values(tenant_id=tenant_id, team_id=team_id, **change))

    async def listed(self, tenant_id: str, team_id: str) -> list[dict[str, Any]]:
        """The team's secrets' metadata; the ciphertext is not selected."""
        cols = [c for c in tool_secrets.c if c.name != "ciphertext"]
        q = sa.select(*cols).where(_of(tenant_id, team_id)).order_by(tool_secrets.c.name)
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def page(
        self,
        tenant_id: str,
        team_id: str,
        search: str,
        *,
        offset: int,
        limit: int,
        template_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """One page of the team's secrets whose name contains `search`, by name; the ciphertext is not selected, and
        LIMIT and OFFSET run in the query."""
        cols = [c for c in tool_secrets.c if c.name != "ciphertext"]
        q = (
            sa.select(*cols)
            .where(self._matching(tenant_id, team_id, search, template_id))
            .order_by(sa.func.lower(tool_secrets.c.name))
        )
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q.offset(offset).limit(limit))).mappings()]

    async def count(self, tenant_id: str, team_id: str, search: str, template_id: str | None = None) -> int:
        q = (
            sa.select(sa.func.count())
            .select_from(tool_secrets)
            .where(self._matching(tenant_id, team_id, search, template_id))
        )
        async with self.engine.connect() as c:
            return int((await c.execute(q)).scalar_one())

    @staticmethod
    def _matching(tenant_id: str, team_id: str, search: str, template_id: str | None = None) -> sa.ColumnElement[bool]:
        named = sa.and_(_of(tenant_id, team_id), contains(tool_secrets.c.name, search))
        return named if template_id is None else sa.and_(named, tool_secrets.c.template_id == template_id)

    async def create(
        self,
        tenant_id: str,
        team_id: str,
        name: str,
        ciphertext: str,
        *,
        actor: str,
        at: datetime,
        template: dict[str, str] | None = None,
        connection_id: str | None = None,
    ) -> bool:
        """False when the team already has the name (nothing written). `template` carries the provisioner's
        `template_id` and `protection` (c-180); `connection_id` marks a connection's secret part (c-330)."""
        row = {"tenant_id": tenant_id, "team_id": team_id, "name": name, "ciphertext": ciphertext, "version": 1}
        if connection_id is not None:
            row["connection_id"] = connection_id
        row |= template or {}
        async with self.engine.begin() as c:
            try:
                async with c.begin_nested():
                    await c.execute(tool_secrets.insert().values(**row, created_by=actor, created_at=at))
            except IntegrityError:
                return False
            change = {"name": name, "action": "created", "version": 1, "actor": actor, "at": at}
            await self._audit(c, tenant_id, team_id, change)
        return True

    async def rotate(
        self, tenant_id: str, team_id: str, name: str, ciphertext: str, *, actor: str, at: datetime
    ) -> int | None:
        """The new version, or None when the team has no such secret."""
        async with self.engine.begin() as c:
            q = (
                tool_secrets.update()
                .where(_of(tenant_id, team_id), tool_secrets.c.name == name)
                .values(ciphertext=ciphertext, version=tool_secrets.c.version + 1, rotated_at=at)
                .returning(tool_secrets.c.version)
            )
            version = (await c.execute(q)).scalar()
            if version is None:
                return None
            change = {"name": name, "action": "rotated", "version": version, "actor": actor, "at": at}
            await self._audit(c, tenant_id, team_id, change)
            return int(version)

    async def delete(self, tenant_id: str, team_id: str, name: str, *, actor: str, at: datetime) -> bool:
        async with self.engine.begin() as c:
            q = (
                tool_secrets.delete()
                .where(_of(tenant_id, team_id), tool_secrets.c.name == name)
                .returning(tool_secrets.c.version)
            )
            version = (await c.execute(q)).scalar()
            if version is None:
                return False
            change = {"name": name, "action": "deleted", "version": version, "actor": actor, "at": at}
            await self._audit(c, tenant_id, team_id, change)
            return True

    async def use(
        self, tenant_id: str, team_id: str, names: list[str], *, actor: str, tool: str, at: datetime
    ) -> dict[str, tuple[str, int]]:
        """The ciphertext and version of each named secret the team has, recording the use of each in one
        transaction. Read on every call, never cached, so a rotation applies to the next call."""
        if not names:
            return {}
        async with self.engine.begin() as c:
            q = sa.select(tool_secrets.c.name, tool_secrets.c.ciphertext, tool_secrets.c.version).where(
                _of(tenant_id, team_id), tool_secrets.c.name.in_(names)
            )
            found = {r.name: (r.ciphertext, int(r.version)) for r in await c.execute(q)}
            if found:
                await c.execute(
                    tool_secrets.update()
                    .where(_of(tenant_id, team_id), tool_secrets.c.name.in_(list(found)))
                    .values(last_used_at=at)
                )
            for name, (_, version) in found.items():
                change = {"name": name, "action": "used", "version": version, "actor": actor, "tool": tool, "at": at}
                await self._audit(c, tenant_id, team_id, change)
        return found

    async def audit(self, tenant_id: str, team_id: str) -> list[dict[str, Any]]:
        mine = (secret_audit.c.tenant_id == tenant_id, secret_audit.c.team_id == team_id)
        q = secret_audit.select().where(*mine).order_by(secret_audit.c.id)
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]
