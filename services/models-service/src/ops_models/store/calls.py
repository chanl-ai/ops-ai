"""The model call log: one row per authenticated completion, a denial included, holding metadata and never a prompt
or a completion."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

import sqlalchemy as sa

from ops_store import Guarantee
from ops_store.database import Database
from ops_store.dialect import db_after

from .tables import model_call_log as t


class CallLog:
    # A row's time is the database's (its default), and the rate window is measured on the same clock (CLOCK).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CLOCK})

    def __init__(self, db: Database) -> None:
        self.db = db

    async def record(self, row: Mapping[str, Any]) -> None:
        async with self.db.begin() as c:
            await c.execute(t.insert().values(**row))

    async def spent(self, key_id: str, *, run_id: str | None = None, since: datetime | None = None) -> Decimal:
        """What the call log records the key spent: on one run (`run_id`), or since a time."""
        q = sa.select(sa.func.coalesce(sa.func.sum(t.c.cost), 0)).where(t.c.key_id == key_id)
        if run_id is not None:
            q = q.where(t.c.run_id == run_id)
        if since is not None:
            q = q.where(t.c.created_at >= since)
        async with self.db.connect() as c:
            return Decimal(str((await c.execute(q)).scalar_one()))

    async def recent(self, key_id: str) -> int:
        """How many calls the key made in the last minute."""
        q = sa.select(sa.func.count()).where(t.c.key_id == key_id, t.c.created_at > db_after(-60))
        async with self.db.connect() as c:
            return int((await c.execute(q)).scalar_one())

    async def page(
        self,
        *,
        key_id: str | None = None,
        alias: str | None = None,
        outcome: str | None = None,
        thread_id: str | None = None,
        limit: int = 100,
    ) -> tuple[list[dict[str, Any]], list[tuple[str, int, Decimal]]]:
        """The newest `limit` rows that match, and per key the number of matching calls and their cost."""
        given = {"key_id": key_id, "alias": alias, "outcome": outcome, "thread_id": thread_id}
        where = [t.c[name] == value for name, value in given.items() if value]
        q = t.select().where(*where).order_by(t.c.created_at.desc()).limit(limit)
        totals = (
            sa.select(t.c.key_id, sa.func.count(), sa.func.coalesce(sa.func.sum(t.c.cost), 0))
            .where(*where)
            .group_by(t.c.key_id)
        )
        async with self.db.connect() as c:
            rows = [dict(r) for r in (await c.execute(q)).mappings()]
            by_key = [(str(k), int(n), s) for k, n, s in await c.execute(totals)]
        return rows, by_key
