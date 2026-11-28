"""The model call log: one row per authenticated completion, a denial included, holding metadata and never a prompt
or a completion. A call that names a tenant is that tenant's row; one that names none, refused or served, is a row
of model_calls_untenanted. Either way the key's spend per period moves in the same transaction (`CallLog.record`
opens one when no request has), which is what its caps read."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import ClassVar, NotRequired, TypedDict

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.http import ListResult, Out
from ops_service_kit.listing import ListParams
from ops_store import Guarantee, background, isolation
from ops_store.dialect import insert_ignore
from ops_store.listing import list_page
from ops_store.rows import rows
from ops_store.search import contains
from ops_store.store import Store

from .provider_keys import ROLE
from .tables import SPEND_KEPT_IDLE_S
from .tables import model_call_log as t
from .tables import model_calls_untenanted as untenanted_calls
from .tables import model_key_spend as spend

# Why a key's spend and the calls that name no tenant are read and written with no tenant (`Store.install_tx`): a
# key's caps sum what it spent for every tenant, and a call that names no tenant has none to be held to.
KEY_SPEND = "model_key_spend"


# The sweep of a key's day and run spend once idle for SPEND_KEPT_IDLE_S (its `sec:` rows go sooner, in `record`).
SPEND_SWEEP = background.register(
    background.retention(spend, spend.c.last_call_s, SPEND_KEPT_IDLE_S, key="models_spend_retention", service="models")
).key

# The rate limit's window, and how long a second's count is kept past it.
RATE_WINDOW = timedelta(seconds=60)
KEPT = timedelta(seconds=120)


class CallLogRow(TypedDict):
    """One call's row in the call log (`store.tables._call_columns`, with its tenant and images)."""

    id: str
    key_id: str
    alias: str
    sensitivity: str | None
    tenant_id: str | None
    # Each sent only by the caller that has it (a chat call's thread, an embedding's none).
    run_id: NotRequired[str | None]
    step_id: NotRequired[str | None]
    thread_id: NotRequired[str | None]
    request_hash: NotRequired[str | None]
    images: int
    input_tokens: int
    output_tokens: int
    cost: Decimal
    latency_ms: int
    outcome: str
    reason: str | None
    # Unset on a call refused before an alias version was chosen.
    alias_version: NotRequired[int | None]
    provider_model: NotRequired[str | None]
    # Set only by a replay or a test that places a call in the past; the table defaults it to now.
    created_at: NotRequired[datetime]


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


class CallList(ListResult[CallRow]):
    """A page of calls, and per key every matching call's count and cost: a sum over the list, which facets (counts
    per value) cannot hold."""

    by_key: list[KeyTotal]


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
        async with self.install_tx(KEY_SPEND, tables=(spend,)) as c:
            found = (await c.execute(q)).all()
        amounts = {p: Decimal(str(a)) for p, a, _ in found}
        recent = sum(int(n) for p, _, n in found if p.startswith("sec:"))
        return CapTotals(
            today=amounts.get(day, Decimal(0)), run=amounts.get(run, Decimal(0)) if run else Decimal(0), recent=recent
        )

    async def record(
        self,
        key_id: str,
        cost: Decimal,
        run_id: str | None,
        now: datetime,
        *,
        untenanted: sa.Executable | None,
        once: bool = False,
        rated: bool = True,
    ) -> bool:
        """Adds one call to its key's second, day and run, and writes the call's row here (`untenanted`) when it named
        no tenant. With `once` (a replay's row, written if its id is not), False and nothing added when it was not.
        A call not `rated` (a replayed answer, which reached no provider) skips the second the rate limit counts."""
        second = _second(now)
        periods = {f"day:{now.date().isoformat()}": second}
        if rated:
            periods[f"sec:{int(second.timestamp())}"] = second
        if run_id:
            periods[f"run:{run_id}"] = second
        async with self.install_tx(KEY_SPEND, tables=(untenanted_calls, spend)) as c:
            if untenanted is not None:
                written = (await c.execute(untenanted)).rowcount
                if once and not written:
                    return False
            for period, starts_at in periods.items():
                await _add(c, key_id, period, starts_at, cost, at_s=now.timestamp())
            stale = sa.and_(spend.c.key_id == key_id, spend.c.period.like("sec:%"), spend.c.starts_at < now - KEPT)
            await c.execute(spend.delete().where(stale))
        return True

    def sweep_tx(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """The transaction one pass of the spend sweep deletes in: install-wide, as the rows are every tenant's."""
        return self.install_tx(KEY_SPEND, tables=(spend,))

    async def keep_sweeping(self, stop: asyncio.Event, *, every_s: float | None = None) -> None:
        """The listed spend sweep, one pass an hour (or every `every_s`), reported on /health/background."""

        def tx() -> AbstractAsyncContextManager[AsyncConnection]:
            # Looked up on each pass, so a pass reaches the store as it is then.
            return self.sweep_tx()

        await background.run_sweep(SPEND_SWEEP, tx, stop=stop, every_s=every_s)


async def _written(store: Store, c: AsyncConnection, row: sa.Insert, *, once: bool) -> bool:
    """Writes a tenant's call row; with `once`, in a savepoint, and False when its id is already written (a replay of
    a call charged before), the request's transaction left usable."""
    if not once:
        await c.execute(row)
        return True
    try:
        async with store.attempt(c):
            await c.execute(row)
    except IntegrityError:
        return False
    return True


async def _add(
    c: AsyncConnection, key_id: str, period: str, starts_at: datetime, amount: Decimal, *, at_s: float
) -> None:
    """Adds in the database (amount = amount + n), so concurrent calls never lose one another's spend: an update,
    then an insert of the first row, then the update again when a concurrent call inserted it first."""
    where = (spend.c.key_id == key_id, spend.c.period == period)
    bump = (
        spend.update()
        .where(*where)
        .values(
            amount=spend.c.amount + amount,
            calls=spend.c.calls + 1,
            last_call_s=sa.case((spend.c.last_call_s < at_s, at_s), else_=spend.c.last_call_s),
        )
    )
    if (await c.execute(bump)).rowcount:
        return
    first = {
        "key_id": key_id,
        "period": period,
        "amount": amount,
        "calls": 1,
        "starts_at": starts_at,
        "last_call_s": at_s,
    }
    if not (await c.execute(insert_ignore(c, spend, first, keys=["key_id", "period"]))).rowcount:
        await c.execute(bump)


class CallLog(Store):
    """The tenant's own calls, run as ROLE in that tenant so the database holds each row to it; the key's spend moves
    with each row (`KeySpend`)."""

    role = ROLE

    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__(engine)
        self.spend = KeySpend(engine)

    async def record(self, row: CallLogRow, *, at: datetime | None = None, once: bool = False) -> bool:
        """Writes the call's row, in the current tenant's log when it names a tenant, and its key's spend, in one
        transaction: the request's when one is open, else one of its own, so a row never commits without its spend.
        A replay passes `at`, when the provider answered, so the spend lands in that call's day, and `once`: False,
        and nothing written, when the call's id already has its row."""
        now = at or datetime.now(UTC)
        untenanted = None
        cost, run_id = Decimal(str(row.get("cost") or 0)), row.get("run_id")
        async with isolation.request_transaction():
            if row.get("tenant_id"):
                async with self.tx() as c:
                    if not await _written(self, c, t.insert().values(**row), once=once):
                        return False
            else:
                values = {k: v for k, v in row.items() if k != "tenant_id"}
                # A replay's row skips an id already written: an install-wide block takes no savepoint.
                untenanted = (
                    insert_ignore(self.engine, untenanted_calls, values, keys=["id"])
                    if once
                    else untenanted_calls.insert().values(**values)
                )
            run = str(run_id) if run_id else None
            rated = row.get("outcome") != "replayed"
            return await self.spend.record(
                str(row["key_id"]), cost, run, now, untenanted=untenanted, once=once, rated=rated
            )

    async def totals(self, key_id: str, now: datetime, *, run_id: str | None = None) -> CapTotals:
        return await self.spend.totals(key_id, now, run_id=run_id)

    async def page(
        self,
        params: ListParams,
        *,
        key_id: str | None = None,
        alias: str | None = None,
        outcome: str | None = None,
        thread_id: str | None = None,
    ) -> CallList:
        """One page of the tenant's matching calls on the shared list contract, newest first, and per key the number
        of all matching calls and their cost, read in one transaction so the totals count the rows the page counts.
        `search` matches the key, the alias or the outcome; `ids` names exact rows whatever the search says."""
        given = {"key_id": key_id, "alias": alias, "outcome": outcome, "thread_id": thread_id}
        where = [t.c[name] == value for name, value in given.items() if value]
        words = (params.search or "").strip()
        if params.ids is not None:
            where.append(t.c.id.in_(params.ids))
        elif words:
            # Here rather than list_page's `search`, so the key totals count the same rows as the page.
            where.append(sa.or_(*(contains(c, words) for c in (t.c.key_id, t.c.alias, t.c.outcome))))
        totals = (
            sa.select(
                t.c.key_id,
                sa.func.count(t.c.id).label("calls"),
                sa.func.coalesce(sa.func.sum(t.c.cost), 0).label("cost"),
            )
            .where(*where)
            .group_by(t.c.key_id)
        )
        query = sa.select(*LISTED).where(*where)
        async with self.tx() as c:
            page = await list_page(
                c,
                query,
                params,
                sortable={"createdAt": t.c.created_at},
                default_sort=t.c.created_at.desc(),
            )
            by_key = await rows(c, totals, KeyTotal)
        return CallList.model_validate({**page, "by_key": by_key})
