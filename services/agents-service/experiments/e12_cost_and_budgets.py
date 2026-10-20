"""E12: the write and read overhead metering adds to each model call, on the compose PostgreSQL. No model calls.

Per call the agents service makes one budget check (budget row plus a sum over the thread's usage rows) before the
call and one usage row insert after it. This times both, p50 and p95, as a thread's row count grows, because the sum
reads every row of the thread.

  make -C services/agents-service db-up migrate
  uv run python experiments/e12_cost_and_budgets.py
"""

from __future__ import annotations

import asyncio
import statistics
import time
from decimal import Decimal

from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.graphs.metering import CallSite
from ops_agents.store.model_calls import model_call_records
from ops_agents.store.usage import UsageLedger, thread_budgets
from ops_metering import Budget, PriceTable, Usage
from ops_service_kit.ids import new_id
from ops_service_kit.settings import Settings

CALLS_PER_THREAD = 400
THREADS = 5
PRICES = PriceTable.parse({"gpt-5.5": {"input": "1.25", "output": "10"}})


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(p * (len(xs) - 1)))]


def row(label: str, c: list[float], r: list[float]) -> str:
    check = f"{statistics.median(c):.2f} / {pct(c, 0.95):.2f}"
    record = f"{statistics.median(r):.2f} / {pct(r, 0.95):.2f}"
    return f"| {label} | {check} | {record} |"


async def main() -> None:
    engine = create_async_engine(Settings().database_url)
    ledger = UsageLedger(engine, PRICES)
    check: dict[int, list[float]] = {}
    record: dict[int, list[float]] = {}
    threads = [new_id("e12") for _ in range(THREADS)]
    try:
        for tid in threads:
            await ledger.set_budget(tid, Budget(max_calls=CALLS_PER_THREAD * 2, max_cost=Decimal(100)))
            for i in range(CALLS_PER_THREAD):
                bucket = i // 100 * 100
                t0 = time.perf_counter()
                await ledger.exhausted(tid)
                t1 = time.perf_counter()
                await ledger.record(CallSite(tid, "run_e12", "draft"), "draft", "gpt-5.5", Usage(600, 50))
                t2 = time.perf_counter()
                check.setdefault(bucket, []).append((t1 - t0) * 1000)
                record.setdefault(bucket, []).append((t2 - t1) * 1000)
        print(f"{THREADS} threads x {CALLS_PER_THREAD} calls, compose PostgreSQL, unloaded")
        print("| Rows already in the thread | Check p50 / p95 ms | Record p50 / p95 ms |")
        print("|---|---|---|")
        for bucket in sorted(check):
            print(row(f"{bucket}-{bucket + 99}", check[bucket], record[bucket]))
        allc = [x for v in check.values() for x in v]
        allr = [x for v in record.values() for x in v]
        print(row("all", allc, allr))
        both = [a + b for a, b in zip(allc, allr, strict=True)]
        print(f"Per call, check + record: p50 {statistics.median(both):.2f} ms, p95 {pct(both, 0.95):.2f} ms")
        totals = await ledger.totals(threads[0])
        print(f"Thread total after {CALLS_PER_THREAD} calls: {totals.calls} calls, cost {totals.cost}")
    finally:
        async with engine.begin() as c:
            await c.execute(model_call_records.delete().where(model_call_records.c.thread_id.in_(threads)))
            await c.execute(thread_budgets.delete().where(thread_budgets.c.thread_id.in_(threads)))
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
