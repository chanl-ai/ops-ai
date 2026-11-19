"""A key's spend per period, by failure mode: two first calls for one key and period at the same moment, where the
second's update finds no row yet and its insert meets the first's, so one call's spend or count is lost. Runs on each
database through `KeySpend.record`, two transactions on two connections, the first held open while the second adds."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from ops_models.store.calls import KeySpend
from ops_models.store.tables import model_key_spend as spend
from ops_store import isolation

from .conftest import Models


async def test_two_first_calls_for_one_key_at_once_both_count(models: Models) -> None:
    key_id, now = f"workflow:race-{uuid4().hex[:8]}", datetime.now(UTC)
    store = KeySpend(models.engine)
    held, release = asyncio.Event(), asyncio.Event()

    async def first() -> None:
        # Its rows are inserted and not yet committed while the second call adds.
        async with isolation.request_transaction():
            await store.record(key_id, Decimal("0.25"), "race", now, untenanted=None)
            held.set()
            await release.wait()

    holding = asyncio.ensure_future(first())
    try:
        await asyncio.wait_for(held.wait(), 10)
        racing = asyncio.ensure_future(store.record(key_id, Decimal("0.50"), "race", now, untenanted=None))
        await asyncio.sleep(0.3)  # the second call is now waiting on the first's rows
        release.set()
        await asyncio.wait_for(asyncio.gather(holding, racing), 10)
        found = await store.totals(key_id, now, run_id="race")
    finally:
        release.set()
        async with models.engine.begin() as c:
            await c.execute(spend.delete().where(spend.c.key_id == key_id))
    assert (found.today, found.run, found.recent) == (Decimal("0.75"), Decimal("0.75"), 2), (
        "a concurrent first call was lost"
    )
