"""Thread budgets (E12) and the ledger that records model calls and sums them (the rows live in model_calls.py)."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any, ClassVar

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.graphs.metering import CallSite
from ops_metering import MICRO, Budget, Exhausted, PriceTable, Totals, Usage, cost, exhausted
from ops_service_kit.http import Out
from ops_service_kit.ids import now_iso
from ops_store import Guarantee
from ops_store.dialect import db_now, upsert
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


def _micros(amount: Decimal) -> int:
    return int(amount / MICRO)


def _amount(micros: int | None) -> Decimal:
    return Decimal(micros or 0) * MICRO


def _asked_by(meta: JsonValue) -> str | None:
    """The thread whose agent asked this thread's agent, from the two keys api/agent_calls.py writes on a specialist's
    thread; None for any other thread, a workflow an agent started included, whose spend stays on its own budget.
    Neither key can come from a request body (routers/graphs.py SERVER_META)."""
    if not isinstance(meta, dict):
        return None
    parent = meta.get("parentThreadId")
    return str(parent) if parent and meta.get("calledBy") else None


class UsageLedger(RuntimeStore):
    # A budget check and the usage it admits are read and written in one transaction (TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    """The agents service's `Meter`: records usage rows and checks a thread's budget against their sum."""

    def __init__(self, engine: AsyncEngine, prices: PriceTable) -> None:
        super().__init__(engine)
        self.prices = prices
        self.calls = ModelCallLedger(engine)

    async def record(self, site: CallSite, kind: str, alias: str, usage: Usage) -> None:
        """A metered workflow call (classify, extract, draft, grade): its usage, with no response to replay."""
        await self.calls.record(self._call(site, kind, alias, usage))

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
    ) -> bool:
        """One kernel model request in a graph run, with what replay needs; False if the task already recorded it."""
        call = self._call(site, "model", alias, usage)
        return await self.calls.record(
            replace(call, latency_ms=latency_ms, task=task, request_hash=request_hash, response=response)
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
        started on and never twice."""
        m, t = model_call_records.c, graph_threads.c
        children = sa.select(t.id).where(t.parent_thread_id == thread_id, team_visible(graph_threads))
        spent = [sa.func.coalesce(sa.func.sum(x), 0) for x in (m.calls, m.input_tokens, m.output_tokens, m.cost_micros)]
        per_thread = (
            sa.select(
                m.thread_id,
                *(s.label(n) for s, n in zip(spent, ("calls", "tokens_in", "tokens_out", "micros"), strict=True)),
            )
            .where(sa.or_(m.thread_id == thread_id, m.thread_id.in_(children)))
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
        async with self.tx() as c:
            found: list[tuple[Any, ...]] = [tuple(r) for r in (await c.execute(q)).all()]
        counted = [r for r in found if r[0] == thread_id or _asked_by(r[5]) == thread_id]
        calls, tokens_in, tokens_out, micros = (sum(int(r[i]) for r in counted) for i in (1, 2, 3, 4))
        return Totals(calls, tokens_in, tokens_out, _amount(micros))

    async def totals_by_run(self, thread_id: str) -> dict[str | None, Totals]:
        return await self.calls.sums(thread_id, by_run=True)

    async def budget(self, thread_id: str) -> Budget | None:
        q = sa.select(_t.max_calls, _t.max_tokens, _t.max_cost_micros).where(_t.thread_id == thread_id)
        async with self.tx() as c:
            row = await one(c, q, BudgetOut)
        if row is None:
            return None
        cap = _amount(row.max_cost_micros) if row.max_cost_micros is not None else None
        return Budget(row.max_calls, row.max_tokens, cap)

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
        budget = await self.budget(thread_id)
        if budget is None or budget.is_empty():
            return None
        return exhausted(await self.totals(thread_id), budget)

    async def chain_root(self, thread_id: str) -> str:
        """The thread whose budget `thread_id`'s model calls count against: itself, or for a specialist's thread the
        thread its chain started on, read from what api/agent_calls.py wrote when the specialist was asked."""
        q = sa.select(graph_threads.c.meta).where(graph_threads.c.id == thread_id, team_visible(graph_threads))
        async with self.tx() as c:
            meta: JsonValue = (await c.execute(q)).scalar_one_or_none()
        asked = _asked_by(meta)
        if asked is None or not isinstance(meta, dict):
            return thread_id
        chain = meta.get("chain")
        return str((chain.get("rootThreadId") if isinstance(chain, dict) else None) or asked)

    async def spent_before_call(self, thread_id: str) -> str | None:
        """Asked before every model call of a graph run: the thread whose spent budget the call would count against,
        or None when the call may run. `totals` counts a chain one call deep, as deep as chains go today
        (ops_contracts.chain.MAX_DEPTH)."""
        root = await self.chain_root(thread_id)
        return root if await self.exhausted(root) is not None else None
