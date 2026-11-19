"""A key's spend rows per day and run are swept once idle, by failure mode: a past day or an idle run is kept for ever;
a run that started before the window and is still going loses its earlier spend, so its cap lets it spend again; a
sweep pass that fails reads as running on /health/background."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx

from ops_models.app import create_models_app
from ops_models.store.calls import SPEND_SWEEP, KeySpend
from ops_models.store.tables import SPEND_KEPT_IDLE_S
from ops_store import background
from ops_store.testing import loop_reports_failure

from .conftest import Models


async def test_a_sweep_drops_idle_days_and_runs_and_keeps_a_long_running_runs_total(models: Models) -> None:
    spend, key = KeySpend(models.engine), f"workflow:sweep-{uuid4().hex[:8]}"
    now = datetime.now(UTC)
    idle = now - timedelta(seconds=SPEND_KEPT_IDLE_S + 86400)
    await spend.record(key, Decimal("0.30"), "run_long", idle, untenanted=None)
    await spend.record(key, Decimal("0.20"), "run_idle", idle, untenanted=None)
    await spend.record(key, Decimal("0.10"), "run_long", now, untenanted=None)
    process = background.BY_KEY[SPEND_SWEEP]
    assert process.sweep is not None
    async with spend.sweep_tx() as c:
        await process.sweep(c, now.timestamp())
    long_run, idle_run, idle_day = (
        await spend.totals(key, now, run_id="run_long"),
        await spend.totals(key, now, run_id="run_idle"),
        await spend.totals(key, idle),
    )
    assert long_run.run == Decimal("0.40"), "a run still going lost the spend from before the window"
    assert (idle_run.run, idle_day.today, long_run.today) == (Decimal(0), Decimal(0), Decimal("0.10"))


async def test_a_spend_sweep_pass_that_raises_shows_on_health(models: Models) -> None:
    spend, stop = KeySpend(models.engine), asyncio.Event()
    app = create_models_app(models.engine, background=[lambda: spend.keep_sweeping(stop, every_s=0.05)])

    def broken(*_: object, **__: object) -> object:
        raise ConnectionError("database connection refused")

    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://models")
    async with app.router.lifespan_context(app), http as client:
        for _ in range(100):
            listed = (await client.get("/health/background")).json()["processes"]
            if any(p["key"] == SPEND_SWEEP and p["lastRunAt"] for p in listed):
                break
            await asyncio.sleep(0.05)
        await loop_reports_failure(client, "models_spend_retention", lambda: setattr(spend, "sweep_tx", broken))
    stop.set()
