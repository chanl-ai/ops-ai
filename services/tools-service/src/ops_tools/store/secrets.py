"""Tool secrets at rest: only ciphertext (`secrets.cipher`), never a value, and an audit row for every create,
rotate, delete and use, written in the same transaction as the change it records."""

from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_store import Guarantee

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

    async def create(self, tenant_id: str, name: str, ciphertext: str, *, actor: str, at: datetime) -> bool:
        """False when the name is taken (nothing written)."""
        row = {"tenant_id": tenant_id, "name": name, "ciphertext": ciphertext, "version": 1}
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
        self, tenant_id: str, names: list[str], *, actor: str, tool: str, at: datetime
    ) -> dict[str, tuple[str, int]]:
        """The ciphertext and version of each named secret that exists, recording the use of each in one transaction.
        Read on every call, never cached, so a rotation applies to the next call."""
        if not names:
            return {}
        async with self.engine.begin() as c:
            q = sa.select(tool_secrets.c.name, tool_secrets.c.ciphertext, tool_secrets.c.version).where(
                tool_secrets.c.tenant_id == tenant_id, tool_secrets.c.name.in_(names)
            )
            found = {r.name: (r.ciphertext, int(r.version)) for r in await c.execute(q)}
            if found:
                await c.execute(
                    tool_secrets.update()
                    .where(tool_secrets.c.tenant_id == tenant_id, tool_secrets.c.name.in_(list(found)))
                    .values(last_used_at=at)
                )
            for name, (_, version) in found.items():
                change = {"name": name, "action": "used", "version": version, "actor": actor, "tool": tool, "at": at}
                await self._audit(c, tenant_id, change)
        return found

    async def audit(self, tenant_id: str) -> list[dict[str, Any]]:
        q = secret_audit.select().where(secret_audit.c.tenant_id == tenant_id).order_by(secret_audit.c.id)
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]
