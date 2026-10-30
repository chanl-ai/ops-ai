"""Thread budgets (E12) and the ledger that records model calls and sums them (the rows live in model_calls.py)."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.graphs.metering import CallSite
from ops_metering import MICRO, Budget, Exhausted, PriceTable, Totals, Usage, cost, exhausted
from ops_service_kit.ids import now_iso
from ops_store import Guarantee
from ops_store.dialect import upsert

from .base import metadata
from .model_calls import ModelCall, ModelCallLedger

thread_budgets = sa.Table(
    "thread_budgets",
    metadata,
    sa.Column("thread_id", sa.String(64), primary_key=True),
    sa.Column("max_calls", sa.Integer()),
    sa.Column("max_tokens", sa.BigInteger()),
    sa.Column("max_cost_micros", sa.BigInteger()),
    sa.Column("updated_at", sa.String(40), nullable=False),
)


def _micros(amount: Decimal) -> int:
    return int(amount / MICRO)


def _amount(micros: int | None) -> Decimal:
    return Decimal(micros or 0) * MICRO


class UsageLedger:
    # A budget check and the usage it admits are read and written in one transaction (TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    """The agents service's `Meter`: records usage rows and checks a thread's budget against their sum."""

    def __init__(self, engine: AsyncEngine, prices: PriceTable) -> None:
        self.engine = engine
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
        return (await self.calls.sums(thread_id, by_run=False)).get(None, Totals())

    async def totals_by_run(self, thread_id: str) -> dict[str | None, Totals]:
        return await self.calls.sums(thread_id, by_run=True)

    async def budget(self, thread_id: str) -> Budget | None:
        async with self.engine.connect() as c:
            row = (
                (await c.execute(thread_budgets.select().where(thread_budgets.c.thread_id == thread_id)))
                .mappings()
                .first()
            )
        if row is None:
            return None
        return Budget(
            row["max_calls"],
            row["max_tokens"],
            _amount(row["max_cost_micros"]) if row["max_cost_micros"] is not None else None,
        )

    async def set_budget(self, thread_id: str, budget: Budget) -> None:
        values: dict[str, Any] = {
            "thread_id": thread_id,
            "max_calls": budget.max_calls,
            "max_tokens": budget.max_tokens,
            "max_cost_micros": _micros(budget.max_cost) if budget.max_cost is not None else None,
            "updated_at": now_iso(),
        }
        async with self.engine.begin() as c:
            await c.execute(upsert(c, thread_budgets, values, keys=["thread_id"]))

    async def update_budget(self, thread_id: str, budget: Budget) -> None:
        current = await self.budget(thread_id) or Budget()
        await self.set_budget(thread_id, current.updated(budget))

    async def exhausted(self, thread_id: str) -> Exhausted | None:
        budget = await self.budget(thread_id)
        if budget is None or budget.is_empty():
            return None
        return exhausted(await self.totals(thread_id), budget)
