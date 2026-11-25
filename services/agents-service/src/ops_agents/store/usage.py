"""Thread budgets (E12) and the ledger that reserves, records and sums model calls (the rows live in model_calls.py).

A call that counts against a budget is reserved before it runs (`UsageLedger.reserve`): in one transaction that holds
the budget's row, the ledger sums what is recorded with what is reserved and still running, refuses the call when a
cap is reached, and otherwise writes the call's reservation. Calls made at once therefore queue on the budget row and
each sees the ones admitted before it, where a check that only read recorded rows let every call in flight pass
together. The call's record replaces its reservation when it returns; a call that failed releases it.

What a reservation holds: one call, and an estimate of the call's output tokens (the call's own maximum, or
`RESERVED_OUTPUT_TOKENS` when it sets none) at the alias's output price. Input tokens are not estimated, so a token or
cost cap can still be passed by the input of the calls in flight and by the one call that crosses it; a call cap
cannot be passed by a checked call. A reservation stops counting after `RESERVED_SECONDS`, so a process that died
mid-call does not hold budget for good."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_agents.graphs.metering import CallSite, Refused, Reservation
from ops_metering import MICRO, Budget, Exhausted, PriceTable, Totals, Usage, cost, exhausted
from ops_service_kit.http import Out
from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.dialect import db_now, locked, upsert
from ops_store.rows import one
from ops_store.schema import TENANT_SCOPED, system
from ops_store.team_scope import team_visible

from .base import metadata
from .graphs import graph_threads
from .model_calls import UNATTRIBUTED, ModelCall, ModelCallLedger, model_call_records
from .tenancy import RuntimeStore, current_tenant

thread_budgets = sa.Table(
    "thread_budgets",
    metadata,
    sa.Column("thread_id", sa.String(64), primary_key=True),
    sa.Column("max_calls", sa.Integer()),
    sa.Column("max_tokens", sa.BigInteger()),
    sa.Column("max_cost_micros", sa.BigInteger()),
    sa.Column("updated_at", sa.String(40), nullable=False),
    # The thread's tenant, set from the request's or loop's context, never from a body (migration 0104).
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant),
    info=TENANT_SCOPED,
)

# The budgets of gone threads with no tenant to hold them to (0104), kept beside model_call_records_unattributed.
thread_budgets_unattributed = sa.Table(
    "thread_budgets_unattributed",
    metadata,
    sa.Column("thread_id", sa.String(64), primary_key=True),
    sa.Column("max_calls", sa.Integer()),
    sa.Column("max_tokens", sa.BigInteger()),
    sa.Column("max_cost_micros", sa.BigInteger()),
    sa.Column("updated_at", sa.String(40), nullable=False),
    sa.Column("moved_at", sa.DateTime(timezone=True), nullable=False, server_default=db_now()),
    info=system(UNATTRIBUTED),
)


class BudgetOut(Out):
    """A thread's stored limits; None is no limit on that measure."""

    max_calls: int | None
    max_tokens: int | None
    max_cost_micros: int | None


_t = thread_budgets.c

# How long a reservation counts against its budget with no record written: longer than a model call may run, so a
# call still in flight is never dropped from the count, and short enough that a call whose process died frees its
# budget the same hour.
RESERVED_SECONDS = 900
# The output tokens reserved for a call that sets no maximum of its own.
RESERVED_OUTPUT_TOKENS = 4096


def _micros(amount: Decimal) -> int:
    return int(amount / MICRO)


def _amount(micros: int | None) -> Decimal:
    return Decimal(micros or 0) * MICRO


def _iso(at: datetime) -> str:
    """`at` in the form `now_iso` writes, so stored times compare as text."""
    return at.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _budget(row: BudgetOut | None) -> Budget | None:
    if row is None:
        return None
    cap = _amount(row.max_cost_micros) if row.max_cost_micros is not None else None
    return Budget(row.max_calls, row.max_tokens, cap)


def _asked_by(meta: JsonValue) -> str | None:
    """The thread whose agent asked this thread's agent, from the two keys api/agent_calls.py writes on a specialist's
    thread; None for any other thread, a workflow an agent started included, whose spend stays on its own budget.
    Neither key can come from a request body (routers/graphs.py SERVER_META)."""
    if not isinstance(meta, dict):
        return None
    parent = meta.get("parentThreadId")
    return str(parent) if parent and meta.get("calledBy") else None


def _agent_conversation(graph: str) -> bool:
    """Whether a thread on `graph` is an agent's conversation: the shared chat graph or a published agent's own."""
    return graph == "agent_wrapper" or graph.startswith("agent:")


class UsageLedger(RuntimeStore):
    # A budget check and the usage it admits are read and written in one transaction (TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    """The agents service's `Meter`: records usage rows and checks a thread's budget against their sum."""

    def __init__(self, engine: AsyncEngine, prices: PriceTable) -> None:
        super().__init__(engine)
        self.prices = prices
        self.calls = ModelCallLedger(engine)

    async def record(
        self, site: CallSite, kind: str, alias: str, usage: Usage, *, settles: Reservation | None = None
    ) -> None:
        """A metered workflow call (classify, extract, draft, grade): its usage, with no response to replay."""
        await self.calls.record(self._call(site, kind, alias, usage), settles=settles.id if settles else None)

    async def reserve(
        self, site: CallSite, kind: str, alias: str, *, on: str | None = None, max_output_tokens: int | None = None
    ) -> Reservation | Refused | None:
        """Admits one call at `site` against the budget of thread `on` (the site's own thread unless named) and holds
        it there: the reservation, or the cap that refuses it, or None when the thread has no budget and nothing is
        held. One transaction, begun by locking the budget's row, so of two calls reserved at once the second waits
        and counts the first."""
        budget_of = on or site.thread_id
        now = datetime.now(UTC)
        at = _iso(now)
        m = model_call_records.c
        caps = sa.select(_t.max_calls, _t.max_tokens, _t.max_cost_micros).where(_t.thread_id == budget_of)
        async with self.tx() as c:
            # The lock is the transaction's first statement, so everything read after it is read while it is held.
            await c.execute(locked(sa.select(_t.thread_id).where(_t.thread_id == budget_of), thread_budgets))
            budget = _budget(await one(c, caps, BudgetOut))
            if budget is None or budget.is_empty():
                return None
            # This thread's reservations past their time are calls that never returned: dropped here, where the
            # thread next asks, so none outlives the conversation's next call.
            await c.execute(model_call_records.delete().where(m.thread_id == site.thread_id, m.reserved_until <= at))
            if (over := exhausted(await self._spent(c, budget_of, reserved_at=at), budget)) is not None:
                return Refused(budget_of, over)
            tokens = max_output_tokens if max_output_tokens is not None else RESERVED_OUTPUT_TOKENS
            held = self._call(site, kind, alias, Usage(0, tokens, 1))
            reservation = Reservation(new_id("mc"), budget_of)
            await c.execute(
                model_call_records.insert().values(
                    id=reservation.id,
                    created_at=at,
                    reserved_until=_iso(now + timedelta(seconds=RESERVED_SECONDS)),
                    tenant_id=current_tenant(),
                    **held.__dict__,
                )
            )
        return reservation

    async def release(self, reservation: Reservation) -> None:
        """Gives back a reservation whose call did not return a response."""
        await self.calls.release(reservation.id)

    async def reserve_model_call(
        self, site: CallSite, alias: str, *, max_output_tokens: int | None
    ) -> Reservation | Refused | None:
        """Asked before every model call of a graph run: the call reserved against the budget its chain shares, or
        that budget's refusal. None when nothing is held: a thread with no budget, and any thread that is not an
        agent's conversation. A workflow's agent step is checked where the step starts (graphs/metering.py `guard`),
        which pauses it for a person: ending it part-way would hand a half-done step to the next node. `_spent`
        counts a chain one call deep, as deep as chains go today (ops_contracts.chain.MAX_DEPTH)."""
        root = await self.chain_root(site.thread_id)
        if root is None:
            return None
        return await self.reserve(site, "model", alias, on=root, max_output_tokens=max_output_tokens)

    async def record_model_call(
        self,
        site: CallSite,
        alias: str,
        usage: Usage,
        *,
        latency_ms: int,
        task: str | None,
        request_hash: str,
        response: Any,
        settles: Reservation | None = None,
    ) -> bool:
        """One kernel model request in a graph run, with what replay needs; False if the task already recorded it.
        `settles` is the reservation the request ran under, which this record replaces."""
        call = self._call(site, "model", alias, usage)
        return await self.calls.record(
            replace(call, latency_ms=latency_ms, task=task, request_hash=request_hash, response=response),
            settles=settles.id if settles else None,
        )

    async def recorded_response(self, thread_id: str, task: str, request_hash: str) -> Any:
        return await self.calls.response(thread_id, task, request_hash)

    def _call(self, site: CallSite, kind: str, alias: str, usage: Usage) -> ModelCall:
        return ModelCall(
            thread_id=site.thread_id,
            run_id=site.run_id,
            step=site.node,
            kind=kind,
            model_alias=alias,
            calls=usage.calls,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_micros=_micros(cost(usage, self.prices.price(alias))),
        )

    async def totals(self, thread_id: str) -> Totals:
        """What the thread has spent, with what the specialists it asked spent on their own threads. A specialist's
        calls are recorded once, on its thread, and counted here, so a chain's spend is charged to the thread it
        started on and never twice. Recorded calls only: a call still running is not spend a person is shown."""
        async with self.tx() as c:
            return await self._spent(c, thread_id, reserved_at=None)

    async def _spent(self, c: AsyncConnection, thread_id: str, *, reserved_at: str | None) -> Totals:
        """The chain's recorded calls and, when `reserved_at` is given, the reservations still held at that time:
        what a budget check counts."""
        m, t = model_call_records.c, graph_threads.c
        counted = m.reserved_until.is_(None)
        if reserved_at is not None:
            counted = sa.or_(counted, m.reserved_until > reserved_at)
        children = sa.select(t.id).where(t.parent_thread_id == thread_id, team_visible(graph_threads))
        spent = [sa.func.coalesce(sa.func.sum(x), 0) for x in (m.calls, m.input_tokens, m.output_tokens, m.cost_micros)]
        per_thread = (
            sa.select(
                m.thread_id,
                *(s.label(n) for s, n in zip(spent, ("calls", "tokens_in", "tokens_out", "micros"), strict=True)),
            )
            .where(sa.or_(m.thread_id == thread_id, m.thread_id.in_(children)), counted)
            .group_by(m.thread_id)
            .subquery()
        )
        # One statement: each thread's sums with its meta, which says whether a child thread is a specialist's. Only
        # the acting team's threads are joined, so a thread of another team, the first one included, counts nothing.
        q = (
            sa.select(
                per_thread.c.thread_id,
                per_thread.c.calls,
                per_thread.c.tokens_in,
                per_thread.c.tokens_out,
                per_thread.c.micros,
                t.meta,
            )
            .select_from(per_thread.join(graph_threads, t.id == per_thread.c.thread_id))
            .where(team_visible(graph_threads))
        )
        found: list[tuple[Any, ...]] = [tuple(r) for r in (await c.execute(q)).all()]
        chain = [r for r in found if r[0] == thread_id or _asked_by(r[5]) == thread_id]
        calls, tokens_in, tokens_out, micros = (sum(int(r[i]) for r in chain) for i in (1, 2, 3, 4))
        return Totals(calls, tokens_in, tokens_out, _amount(micros))

    async def totals_by_run(self, thread_id: str) -> dict[str | None, Totals]:
        return await self.calls.sums(thread_id, by_run=True)

    async def budget(self, thread_id: str) -> Budget | None:
        q = sa.select(_t.max_calls, _t.max_tokens, _t.max_cost_micros).where(_t.thread_id == thread_id)
        async with self.tx() as c:
            return _budget(await one(c, q, BudgetOut))

    async def set_budget(self, thread_id: str, budget: Budget) -> None:
        values = {
            "thread_id": thread_id,
            "max_calls": budget.max_calls,
            "max_tokens": budget.max_tokens,
            "max_cost_micros": _micros(budget.max_cost) if budget.max_cost is not None else None,
            "updated_at": now_iso(),
            "tenant_id": current_tenant(),
        }
        async with self.tx() as c:
            await c.execute(upsert(c, thread_budgets, values, keys=["thread_id"]))

    async def update_budget(self, thread_id: str, budget: Budget) -> None:
        current = await self.budget(thread_id) or Budget()
        await self.set_budget(thread_id, current.updated(budget))

    async def exhausted(self, thread_id: str) -> Exhausted | None:
        """The cap the thread has reached, counting the calls reserved and still running; None while it has room. A
        read only: the call it lets through is admitted by `reserve`."""
        budget = await self.budget(thread_id)
        if budget is None or budget.is_empty():
            return None
        async with self.tx() as c:
            return exhausted(await self._spent(c, thread_id, reserved_at=now_iso()), budget)

    async def chain_root(self, thread_id: str) -> str | None:
        """The thread whose budget an agent's reply on `thread_id` counts against: itself, or for a specialist's
        thread the thread its chain started on, read from what api/agent_calls.py wrote when the specialist was asked.
        None for a thread that is not an agent's conversation."""
        t = graph_threads.c
        q = sa.select(t.graph, t.meta).where(t.id == thread_id, team_visible(graph_threads))
        async with self.tx() as c:
            row = (await c.execute(q)).first()
        if row is None or not _agent_conversation(str(row[0] or "")):
            return None
        meta: JsonValue = row[1]
        asked = _asked_by(meta)
        if asked is None or not isinstance(meta, dict):
            return thread_id
        chain = meta.get("chain")
        return str((chain.get("rootThreadId") if isinstance(chain, dict) else None) or asked)
