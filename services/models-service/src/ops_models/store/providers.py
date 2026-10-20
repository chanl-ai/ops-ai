"""Provider connections: where an alias version's calls go, and the name of the credential they use (never the
credential itself)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

import sqlalchemy as sa

from ops_store import Guarantee
from ops_store.database import Database
from ops_store.dialect import insert_ignore

from .tables import provider_connections as t


class Providers:
    # A connection's name is unique, so two creates of one name cannot both land (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    def __init__(self, db: Database) -> None:
        self.db = db

    async def all(self) -> list[dict[str, Any]]:
        async with self.db.connect() as c:
            return [dict(r) for r in (await c.execute(t.select().order_by(t.c.name))).mappings()]

    async def get(self, provider_id: str) -> dict[str, Any] | None:
        async with self.db.connect() as c:
            row = (await c.execute(t.select().where(t.c.id == provider_id))).mappings().first()
        return dict(row) if row is not None else None

    async def create(self, row: Mapping[str, Any]) -> bool:
        """Adds a connection; False, and nothing written, when one with the same name exists."""
        async with self.db.begin() as c:
            if (await c.execute(sa.select(t.c.id).where(t.c.name == row["name"]))).first():
                return False
            await c.execute(t.insert().values(**row))
        return True

    async def rebind(self, provider_id: str, base_url: str, key_ref: str | None) -> None:
        async with self.db.begin() as c:
            await c.execute(t.update().where(t.c.id == provider_id).values(base_url=base_url, key_ref=key_ref))

    async def ensure(self, row: Mapping[str, Any]) -> None:
        """Adds the connection unless one with its id exists, which is left as it is."""
        async with self.db.begin() as c:
            await c.execute(insert_ignore(c, t, row, keys=["id"]))

    async def follow_url(self, provider_id: str, base_url: str) -> None:
        """Points the connection at `base_url` unless it names a credential: one bound to a real provider keeps it."""
        async with self.db.begin() as c:
            await c.execute(t.update().where(t.c.id == provider_id, t.c.key_ref.is_(None)).values(base_url=base_url))
