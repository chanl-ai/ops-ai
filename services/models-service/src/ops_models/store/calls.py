"""The model call log: one row per authenticated completion, a denial included, holding metadata and never a prompt
or a completion. A call that names a tenant is that tenant's row; one that names none, refused or served, is a row
of model_calls_untenanted. Either way the key's spend per period moves in the same transaction (`CallLog.record`
opens one when no request has), which is what its caps read."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.http import Out
from ops_store import Guarantee, isolation
from ops_store.dialect import insert_ignore
from ops_store.rows import rows
from ops_store.store import Store

from .provider_keys import ROLE
from .tables import model_call_log as t
from .tables import model_calls_untenanted as untenanted_calls
from .tables import model_key_spend as spend

# Why a key's spend and the calls that name no tenant are read and written with no tenant (`Store.install_tx`): a
# key's caps sum what it spent for every tenant, and a call that names no tenant has none to be held to.
KEY_SPEND = "model_key_spend"

# The rate limit's window, and how long a second's count is kept past it.
RATE_WINDOW = timedelta(seconds=60)
KEPT = timedelta(seconds=120)


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


class CapTotals(Out):
    """What a key's caps read: its spend today and on one run, and its calls in the last minute."""

    today: Decimal
    run: Decimal
    recent: int


def _second(now: datetime) -> datetime:
    return now.replace(microsecond=0)


class KeySpend(Store):
    """Per key and period, what it spent and how many calls it made, across every tenant; and the calls that named no
    tenant. Install tables, run as the service's own login."""

    # Spend is added in the database (amount = amount + n), so concurrent calls never lose one another's count, and it
    # moves in the transaction of the call's row (CAS, TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    async def totals(self, key_id: str, now: datetime, *, run_id: str | None = None) -> CapTotals:
        """The key's spend since `now`'s UTC midnight and on `run_id`, and its calls in the seconds that overlap the
        last minute (a second counts while any part of it is inside the window)."""
        day, run = f"day:{now.date().isoformat()}", f"run:{run_id}" if run_id else None
        rate = sa.and_(spend.c.period.like("sec:%"), spend.c.starts_at > now - RATE_WINDOW - timedelta(seconds=1))
        periods = [p for p in (day, run) if p]
        q = sa.select(spend.c.period, spend.c.amount, spend.c.calls).where(
            spend.c.key_id == key_id, sa.or_(spend.c.period.in_(periods), rate)
        )
        async with self.install_tx(KEY_SPEND) as c:
            found = (await c.execute(q)).all()
        amounts = {p: Decimal(str(a)) for p, a, _ in found}
        recent = sum(int(n) for p, _, n in found if p.startswith("sec:"))
        return CapTotals(
            today=amounts.get(day, Decimal(0)), run=amounts.get(run, Decimal(0)) if run else Decimal(0), recent=recent
        )

    async def record(
        self, key_id: str, cost: Decimal, run_id: str | None, now: datetime, *, untenanted: sa.Insert | None
    ) -> None:
        """Adds one call to its key's second, day and run, and writes the call's row here (`untenanted`) when it named
        no tenant."""
        second = _second(now)
        periods = {f"sec:{int(second.timestamp())}": second, f"day:{now.date().isoformat()}": second}
        if run_id:
            periods[f"run:{run_id}"] = second
        async with self.install_tx(KEY_SPEND) as c:
            if untenanted is not None:
                await c.execute(untenanted)
            for period, starts_at in periods.items():
                await _add(c, key_id, period, starts_at, cost)
            stale = sa.and_(spend.c.key_id == key_id, spend.c.period.like("sec:%"), spend.c.starts_at < now - KEPT)
            await c.execute(spend.delete().where(stale))


async def _add(c: AsyncConnection, key_id: str, period: str, starts_at: datetime, amount: Decimal) -> None:
    """Adds in the database (amount = amount + n), so concurrent calls never lose one another's spend: an update,
    then an insert of the first row, then the update again when a concurrent call inserted it first."""
    where = (spend.c.key_id == key_id, spend.c.period == period)
    bump = spend.update().where(*where).values(amount=spend.c.amount + amount, calls=spend.c.calls + 1)
    if (await c.execute(bump)).rowcount:
        return
    first = {"key_id": key_id, "period": period, "amount": amount, "calls": 1, "starts_at": starts_at}
    if not (await c.execute(insert_ignore(c, spend, first, keys=["key_id", "period"]))).rowcount:
        await c.execute(bump)


class CallLog(Store):
    """The tenant's own calls, run as ROLE in that tenant so the database holds each row to it; the key's spend moves
    with each row (`KeySpend`)."""

    role = ROLE

    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__(engine)
        self.spend = KeySpend(engine)

    async def record(self, row: Mapping[str, Any]) -> None:
        """Writes the call's row, in the current tenant's log when it names a tenant, and its key's spend, in one
        transaction: the request's when one is open, else one of its own, so a row never commits without its spend."""
        now = datetime.now(UTC)
        untenanted = None
        cost, run_id = Decimal(str(row.get("cost") or 0)), row.get("run_id")
        async with isolation.request_transaction():
            if row.get("tenant_id"):
                async with self.tx() as c:
                    await c.execute(t.insert().values(**row))
            else:
                untenanted = untenanted_calls.insert().values(**{k: v for k, v in row.items() if k != "tenant_id"})
            run = str(run_id) if run_id else None
            await self.spend.record(str(row["key_id"]), cost, run, now, untenanted=untenanted)

    async def totals(self, key_id: str, now: datetime, *, run_id: str | None = None) -> CapTotals:
        return await self.spend.totals(key_id, now, run_id=run_id)

    async def page(
        self,
        *,
        key_id: str | None = None,
        alias: str | None = None,
        outcome: str | None = None,
        thread_id: str | None = None,
        limit: int = 100,
    ) -> tuple[list[CallRow], list[KeyTotal]]:
        """The tenant's newest `limit` rows that match, and per key the number of matching calls and their cost."""
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
        async with self.tx() as c:
            return await rows(c, q, CallRow), await rows(c, totals, KeyTotal)
