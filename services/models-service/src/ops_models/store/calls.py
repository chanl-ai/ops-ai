"""The model call log: one row per authenticated completion, a denial included, holding metadata and never a prompt
or a completion."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

import sqlalchemy as sa

from ops_service_kit.http import Out
from ops_store import Guarantee
from ops_store.dialect import db_after
from ops_store.rows import rows
from ops_store.store import Store

from .tables import model_call_log as t

# Why the log is read and written with no tenant (`Store.install_tx`): a key's caps sum its rows across every tenant,
# and a refusal before any tenant is known still writes its row.
CALL_LOG = "model_call_log"


class CallRow(Out):
    """One call as the list shows it: metadata, never a prompt or a completion."""

    id: str
    key_id: str
    alias: str
    alias_version: int | None
    provider_model: str | None
    input_tokens: int
    output_tokens: int
    cost: Decimal
    latency_ms: int
    outcome: str
    reason: str | None
    run_id: str | None
    step_id: str | None
    thread_id: str | None
    request_hash: str | None
    created_at: datetime
    images: int


class KeyTotal(Out):
    """One key's matching calls and their cost."""

    key_id: str
    calls: int
    cost: Decimal


LISTED = (
    t.c.id,
    t.c.key_id,
    t.c.alias,
    t.c.alias_version,
    t.c.provider_model,
    t.c.input_tokens,
    t.c.output_tokens,
    t.c.cost,
    t.c.latency_ms,
    t.c.outcome,
    t.c.reason,
    t.c.run_id,
    t.c.step_id,
    t.c.thread_id,
    t.c.request_hash,
    t.c.created_at,
    t.c.images,
)


class CallLog(Store):
    # A row's time is the database's (its default), and the rate window is measured on the same clock (CLOCK).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CLOCK})

    async def record(self, row: Mapping[str, Any]) -> None:
        async with self.install_tx(CALL_LOG) as c:
            await c.execute(t.insert().values(**row))

    async def spent(self, key_id: str, *, run_id: str | None = None, since: datetime | None = None) -> Decimal:
        """What the call log records the key spent: on one run (`run_id`), or since a time."""
        q = sa.select(sa.func.coalesce(sa.func.sum(t.c.cost), 0)).where(t.c.key_id == key_id)
        if run_id is not None:
            q = q.where(t.c.run_id == run_id)
        if since is not None:
            q = q.where(t.c.created_at >= since)
        async with self.install_tx(CALL_LOG) as c:
            return Decimal(str((await c.execute(q)).scalar_one()))

    async def recent(self, key_id: str) -> int:
        """How many calls the key made in the last minute."""
        q = sa.select(sa.func.count(t.c.id)).where(t.c.key_id == key_id, t.c.created_at > db_after(-60))
        async with self.install_tx(CALL_LOG) as c:
            return int((await c.execute(q)).scalar_one())

    async def page(
        self,
        *,
        key_id: str | None = None,
        alias: str | None = None,
        outcome: str | None = None,
        thread_id: str | None = None,
        limit: int = 100,
    ) -> tuple[list[CallRow], list[KeyTotal]]:
        """The newest `limit` rows that match, and per key the number of matching calls and their cost."""
        given = {"key_id": key_id, "alias": alias, "outcome": outcome, "thread_id": thread_id}
        where = [t.c[name] == value for name, value in given.items() if value]
        q = sa.select(*LISTED).where(*where).order_by(t.c.created_at.desc()).limit(limit)
        totals = (
            sa.select(
                t.c.key_id,
                sa.func.count(t.c.id).label("calls"),
                sa.func.coalesce(sa.func.sum(t.c.cost), 0).label("cost"),
            )
            .where(*where)
            .group_by(t.c.key_id)
        )
        async with self.install_tx(CALL_LOG) as c:
            return await rows(c, q, CallRow), await rows(c, totals, KeyTotal)
