"""Bank aliases and their immutable versions. A change is a new version, and the newest one not retired serves."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.ids import now_iso
from ops_store import Guarantee
from ops_store.database import Database
from ops_store.dialect import locked

from .tables import model_aliases as t
from .tables import provider_connections as p

SENSITIVITY = ("public", "internal", "confidential", "restricted")


def cleared(alias_ceiling: str, data: str) -> bool:
    """Whether an alias cleared up to `alias_ceiling` may receive data of class `data`; an unknown class never is."""
    if alias_ceiling not in SENSITIVITY or data not in SENSITIVITY:
        return False
    return SENSITIVITY.index(data) <= SENSITIVITY.index(alias_ceiling)


class Aliases:
    # A new version locks the alias's newest row, retires the serving one and inserts the next in one transaction; the
    # primary key (name, version) refuses a second writer's equal number (TRANSACTION, CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.CAS})

    def __init__(self, db: Database) -> None:
        self.db = db

    async def current(self, name: str) -> dict[str, Any] | None:
        """The version serving `name`, with its connection's type, base URL and credential name."""
        async with self.db.connect() as c:
            return await _current(c, name)

    async def all_current(self) -> list[dict[str, Any]]:
        async with self.db.connect() as c:
            names = [r[0] for r in await c.execute(sa.select(t.c.name).distinct().order_by(t.c.name))]
            return [cur for n in names if (cur := await _current(c, n)) is not None]

    async def versions(self, name: str) -> list[dict[str, Any]]:
        async with self.db.connect() as c:
            q = t.select().where(t.c.name == name).order_by(t.c.version)
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def create(self, name: str, kind: str, fields: Mapping[str, Any]) -> bool:
        """Version 1 of a new alias; False, and nothing written, when the alias exists."""
        async with self.db.begin() as c:
            if (await c.execute(sa.select(t.c.name).where(t.c.name == name))).first():
                return False
            await c.execute(t.insert().values(**_row(name, 1, kind, fields)))
        return True

    async def add_version(self, name: str, fields: Mapping[str, Any]) -> int | None:
        """The next version of `name`, which replaces the one serving; None when there is no such alias."""
        async with self.db.begin() as c:
            newest = t.select().where(t.c.name == name).order_by(t.c.version.desc()).limit(1)
            last = (await c.execute(locked(newest, t))).first()
            if last is None:
                return None
            version = int(last.version) + 1
            # One version of an alias is current at a time (ux_model_aliases_current), so the old one is retired in
            # this transaction.
            await c.execute(t.update().where(t.c.name == name, t.c.status == "current").values(status="retired"))
            await c.execute(t.insert().values(**_row(name, version, str(last.kind), fields)))
        return version


async def _current(c: AsyncConnection, name: str) -> dict[str, Any] | None:
    q = (
        sa.select(t, p.c.type, p.c.base_url, p.c.key_ref)
        .join(p, p.c.id == t.c.provider_id)
        .where(t.c.name == name, t.c.status == "current")
        .order_by(t.c.version.desc())
        .limit(1)
    )
    row = (await c.execute(q)).mappings().first()
    return dict(row) if row is not None else None


def _row(name: str, version: int, kind: str, fields: Mapping[str, Any]) -> dict[str, Any]:
    return {**fields, "name": name, "version": version, "kind": kind, "status": "current", "created_at": now_iso()}
