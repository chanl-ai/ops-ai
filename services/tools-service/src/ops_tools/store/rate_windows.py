"""Per-operation call counters for the gateway's rate limit.

One row per tenant, operation and one-minute window on the database clock. Each call that is about to run spends
one with a single atomic upsert, so two gateway processes, or a restarted one, count against the same row and two
calls arriving together cannot both read the last free slot. A window edge can let up to twice the limit through in
any 60 seconds; a sliding window over `gateway_calls` is the upgrade if that matters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import sqlalchemy as sa

from ops_store import Guarantee
from ops_store.dialect import db_after, db_now, insert_ignore
from ops_store.schema import TENANT_SCOPED
from ops_store.store import Store

from .modules import metadata
from .tenancy import ROLE

operation_rate_windows = sa.Table(
    "operation_rate_windows",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    # The operation's name, unique within a tenant (the gateway resolves calls by it).
    sa.Column("operation", sa.String(200), primary_key=True),
    sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
    sa.Column("calls", sa.Integer, nullable=False),
    info=TENANT_SCOPED,
)


@dataclass(frozen=True)
class Spent:
    allowed: bool
    calls: int
    reset_at: str


class RateWindows(Store):
    # The count rises by one atomic statement, so concurrent calls never share a slot (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})
    role = ROLE

    async def spend(self, tenant_id: str, operation: str, limit: int) -> Spent:
        """Counts one call in the current minute; allowed while the count is within `limit`. The window's row is made
        if missing, then raised by one in a single UPDATE, whose row lock makes concurrent calls take turns."""
        t = operation_rate_windows
        key = (t.c.tenant_id == tenant_id, t.c.operation == operation)
        async with self.tx() as c:
            now: datetime = (await c.execute(sa.select(db_now()))).scalar_one()
            start = now.astimezone(UTC).replace(second=0, microsecond=0)
            row = {"tenant_id": tenant_id, "operation": operation, "window_start": start, "calls": 0}
            await c.execute(insert_ignore(c, t, row, keys=["tenant_id", "operation", "window_start"]))
            raised = t.update().where(*key, t.c.window_start == start).values(calls=t.c.calls + 1).returning(t.c.calls)
            calls = int((await c.execute(raised)).scalar_one())
            await c.execute(t.delete().where(*key, t.c.window_start < db_after(-3600)))
        return Spent(allowed=calls <= limit, calls=calls, reset_at=(start + timedelta(minutes=1)).isoformat())
