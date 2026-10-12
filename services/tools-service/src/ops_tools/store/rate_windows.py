"""Per-operation call counters for the gateway's rate limit (c-028).

One row per tenant, operation and one-minute window on the database clock. Each call that is about to run spends
one with a single atomic upsert, so two gateway processes, or a restarted one, count against the same row and two
calls arriving together cannot both read the last free slot. A window edge can let up to twice the limit through in
any 60 seconds; a sliding window over `gateway_calls` is the upgrade if that matters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import Guarantee

from .modules import metadata

operation_rate_windows = sa.Table(
    "operation_rate_windows",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    # The operation's name, unique within a tenant (the gateway resolves calls by it).
    sa.Column("operation", sa.String(200), primary_key=True),
    sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
    sa.Column("calls", sa.Integer, nullable=False),
)


@dataclass(frozen=True)
class Spent:
    allowed: bool
    calls: int
    reset_at: str


class RateWindows:
    # The count rises by one atomic statement, so concurrent calls never share a slot (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def spend(self, tenant_id: str, operation: str, limit: int) -> Spent:
        """Counts one call in the current minute; allowed while the count is within `limit`."""
        t = operation_rate_windows
        window = sa.func.date_trunc("minute", sa.func.now())
        stmt = (
            insert(t)
            .values(tenant_id=tenant_id, operation=operation, window_start=window, calls=1)
            .on_conflict_do_update(
                index_elements=[t.c.tenant_id, t.c.operation, t.c.window_start], set_={"calls": t.c.calls + 1}
            )
            .returning(t.c.calls, t.c.window_start)
        )
        async with self.engine.begin() as c:
            calls, start = (await c.execute(stmt)).one()
            await c.execute(
                t.delete().where(
                    t.c.tenant_id == tenant_id,
                    t.c.operation == operation,
                    t.c.window_start < sa.func.now() - sa.text("interval '1 hour'"),
                )
            )
        return Spent(allowed=int(calls) <= limit, calls=int(calls), reset_at=(start + timedelta(minutes=1)).isoformat())
