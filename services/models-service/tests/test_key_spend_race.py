"""A key's spend per period, by failure mode: two first calls for one key and period at the same moment, where the
second's update finds no row yet and its insert meets the first's, so one call's spend or count is lost. Runs on each
database as the database's owner, two connections, the first holding its insert open while the second adds."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import sqlalchemy as sa

from ops_models.store.calls import _add  # pyright: ignore[reportPrivateUsage]
from ops_models.store.tables import model_key_spend as spend

from .conftest import Models


async def test_two_first_calls_for_one_key_at_once_both_count(models: Models) -> None:
    key_id, period, now = f"workflow:race-{uuid4().hex[:8]}", "day:race", datetime.now(UTC)
    first = await models.engine.connect()
    second = await models.engine.connect()
    try:
        await first.begin()
        await _add(
            first, key_id, period, now, Decimal("0.25"), at_s=now.timestamp()
        )  # the first row, not yet committed
        await second.begin()
        racing = asyncio.ensure_future(_add(second, key_id, period, now, Decimal("0.50"), at_s=now.timestamp()))
        await asyncio.sleep(0.3)  # the second call is now waiting on the first's row
        await first.commit()
        await asyncio.wait_for(racing, 10)
        await second.commit()
        q = sa.select(spend.c.amount, spend.c.calls).where(spend.c.key_id == key_id, spend.c.period == period)
        found = (await first.execute(q)).one()
        await first.execute(spend.delete().where(spend.c.key_id == key_id))
        await first.commit()
    finally:
        await first.close()
        await second.close()
    assert (Decimal(str(found.amount)), found.calls) == (Decimal("0.75"), 2), "a concurrent first call was lost"
