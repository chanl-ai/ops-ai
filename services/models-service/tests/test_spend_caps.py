"""Spend ceilings from the call log, by failure mode: a run that goes on calling past its ceiling, a key that goes on
calling past its daily cap, a ceiling counted by the caller (which a second process, or a retry, gets around) rather
than from what models-service recorded, and spend the provider already charged lost because the settle after its
answer failed or was cancelled."""

from __future__ import annotations

import asyncio
import contextlib
import json
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import event

from ops_models.store import ModelKeys
from ops_service_kit.logging import captured_logging

from .conftest import Models


async def test_a_run_stops_at_its_ceiling_from_its_recorded_spend(models: Models) -> None:
    _, secret = await models.key(budget="5")
    run = {"X-Run-Id": "run_faq_1", "X-Run-Spend-Cap": "0.00001"}
    assert (await models.complete(secret, **run)).status_code == 200, "under the ceiling: answered"
    refused = await models.complete(secret, **run)
    assert refused.status_code == 429 and refused.json()["error"]["code"] == "run_spend_cap", refused.text
    other = await models.complete(secret, **{**run, "X-Run-Id": "run_faq_2"})
    assert other.status_code == 200, "another run has its own ceiling"


async def test_a_key_stops_at_its_daily_cap(models: Models) -> None:
    key_id, secret = await models.key(budget="5")
    await ModelKeys(models.engine).set_daily_cap(key_id, Decimal("0.00001"))
    assert (await models.complete(secret)).status_code == 200
    refused = await models.complete(secret)
    assert refused.status_code == 429 and refused.json()["error"]["code"] == "daily_spend_cap", refused.text
    await ModelKeys(models.engine).set_daily_cap(key_id, None)
    assert (await models.complete(secret)).status_code == 200


async def test_a_keys_caps_count_the_calls_it_made_for_every_tenant(models: Models) -> None:
    """A key spent for many tenants: its daily and run caps are the key's, so a tenant that never called is refused
    once another tenant's calls reached them, and its rate limit counts a refused call too."""
    key_id, secret = await models.key(budget="5", rateLimitPerMinute=2)
    run = {"X-Run-Id": "run_shared_1", "X-Run-Spend-Cap": "0.00001"}
    assert (await models.complete(secret, **run, **{"X-Tenant-Id": "t_a"})).status_code == 200
    refused = await models.complete(secret, **run, **{"X-Tenant-Id": "t_b"})
    assert (refused.status_code, refused.json()["error"]["code"]) == (429, "run_spend_cap"), refused.text
    over = await models.complete(secret, **{"X-Tenant-Id": "t_c"})
    assert (over.status_code, over.json()["error"]["code"]) == (429, "rate_limited"), over.text
    await ModelKeys(models.engine).set_daily_cap(key_id, Decimal("0.00001"))
    daily = await models.complete(secret, **{"X-Tenant-Id": "t_d", "X-Run-Id": "run_shared_2"})
    assert (daily.status_code, daily.json()["error"]["code"]) == (429, "daily_spend_cap"), daily.text


def _on_spend_write(models: Models, act: Any) -> Any:
    """Calls `act` at the settle's first write to the key's spend, after the provider answered."""

    def hook(_c: object, _cur: object, statement: str, *_: object) -> None:
        if "model_key_spend" in statement and not statement.lstrip().upper().startswith("SELECT"):
            act()

    event.listen(models.engine.sync_engine, "before_cursor_execute", hook)
    return lambda: event.remove(models.engine.sync_engine, "before_cursor_execute", hook)


async def test_a_settle_that_fails_after_the_provider_answered_logs_the_spend_to_recover(models: Models) -> None:
    key_id, secret = await models.key(budget="5")

    def fail() -> None:
        raise RuntimeError("the database went away")

    remove = _on_spend_write(models, fail)
    try:
        # The app's error is raised through the test transport.
        with captured_logging("models-settle") as stream, contextlib.suppress(RuntimeError):
            await models.complete(secret, **{"X-Tenant-Id": "local"})
    finally:
        remove()
    lines = [json.loads(x) for x in stream.getvalue().splitlines() if x.startswith("{")]
    lost = [x for x in lines if x.get("event") == "model_call_settle_failed"]
    assert lost and lost[0]["level"] == "error", (
        f"the provider's spend was neither recorded nor logged: {[x.get('event') for x in lines]}"
    )
    assert lost[0]["key_id"] == key_id and lost[0]["input_tokens"] > 0 and Decimal(lost[0]["cost"]) > 0, lost


async def test_a_client_gone_after_the_provider_answered_still_settles(models: Models) -> None:
    key_id, secret = await models.key(budget="5")
    call = asyncio.ensure_future(models.complete(secret, **{"X-Tenant-Id": "local"}))
    gone: list[bool] = []

    def disconnect() -> None:
        if not gone:
            gone.append(True)
            call.cancel()

    remove = _on_spend_write(models, disconnect)
    try:
        with contextlib.suppress(asyncio.CancelledError):
            await call
        for _ in range(100):  # the shielded settle finishes on its own
            if await models.spent(key_id) > 0:
                break
            await asyncio.sleep(0.02)
    finally:
        remove()
    assert gone, "the call never reached its settle"
    assert await models.spent(key_id) > 0, "the client's disconnect rolled back the spend the provider charged"


def _on_key_write(models: Models, act: Any) -> Any:
    """Calls `act` at the settle's write of the key's spent total."""

    def hook(_c: object, _cur: object, statement: str, *_: object) -> None:
        if statement.lstrip().upper().startswith("UPDATE MODEL_KEYS"):
            act()

    event.listen(models.engine.sync_engine, "before_cursor_execute", hook)
    return lambda: event.remove(models.engine.sync_engine, "before_cursor_execute", hook)


async def test_a_stop_right_after_the_provider_answered_still_records_the_spend(models: Models) -> None:
    """The server stops while a settle waits on the database: the stop waits for it, so the spend is recorded before
    the process ends rather than dropped with its unfinished task."""
    key_id, secret = await models.key(budget="5")
    lock = await models.engine.connect()
    await lock.begin()
    # Another writer holds the key's row, so the settle's spend write waits after the provider answered.
    await lock.execute(sa.text("UPDATE model_keys SET status = status WHERE id = :k"), {"k": key_id})
    waiting: list[bool] = []
    remove = _on_key_write(models, lambda: waiting.append(True))
    lifespan = models.app.router.lifespan_context(models.app)
    try:
        await lifespan.__aenter__()
        call = asyncio.ensure_future(models.complete(secret, **{"X-Tenant-Id": "local"}))
        for _ in range(250):
            if waiting:
                break
            await asyncio.sleep(0.02)
        assert waiting, "the call never reached its settle"
        call.cancel()  # the client goes as the server stops
        with contextlib.suppress(asyncio.CancelledError):
            await call
        stopping = asyncio.ensure_future(lifespan.__aexit__(None, None, None))
        await asyncio.sleep(0.3)
        assert not stopping.done(), "the server stopped with a settle still waiting to record its spend"
        await lock.rollback()
        await asyncio.wait_for(stopping, 10)
    finally:
        remove()
        if lock.in_transaction():
            await lock.rollback()
        await lock.close()
    assert await models.spent(key_id) > 0, "the stop dropped the spend the provider charged"
