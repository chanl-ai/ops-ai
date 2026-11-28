"""Spend ceilings from the call log, by failure mode: a run that goes on calling past its ceiling, a key that goes on
calling past its daily cap, a ceiling counted by the caller (which a second process, or a retry, gets around) rather
than from what models-service recorded, and spend the provider already charged lost because the settle after its
answer failed or was cancelled."""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import event

from ops_models.recovery import replay_lines
from ops_models.store import CallLog, ModelKeys
from ops_models.store.calls import SPEND_SWEEP, KeySpend
from ops_models.store.tables import SPEND_KEPT_IDLE_S
from ops_service_kit.logging import captured_logging
from ops_store import background, isolation

from .conftest import Models, accounts


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
    await accounts(models.engine, "t_a", "t_b", "t_c", "t_d")
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


@pytest.mark.parametrize("per_tenant", [False, True], ids=["one_budget", "per_tenant"])
async def test_a_settle_that_fails_still_leaves_the_calls_row(models: Models, per_tenant: bool) -> None:
    """The settle's transaction fails after the provider answered: the call still has its one row, an error with the
    usage the provider charged, so the log never shows fewer calls than were made; and every ledger records that cost
    once: the key's spent total, the tenant's share, and the period totals the day and run caps read."""
    key_id, secret = await models.key(budget="5")
    keys = ModelKeys(models.engine)
    if per_tenant:
        await keys.set_tenant_budget(key_id, Decimal("2"))
    failed: list[bool] = []

    def fail_once() -> None:
        if not failed:
            failed.append(True)
            raise RuntimeError("the database went away")

    remove = _on_spend_write(models, fail_once)
    try:
        with contextlib.suppress(RuntimeError):
            await models.complete(secret, **{"X-Tenant-Id": "local"})
    finally:
        remove()
    assert failed, "the call never reached its settle"
    rows = await models.calls(key_id)
    assert [(r["outcome"], r["reason"]) for r in rows] == [("error", "settle_failed")], rows
    assert rows[0]["inputTokens"] > 0, rows
    charged = Decimal(rows[0]["cost"])
    assert charged > 0, rows
    today = (await CallLog(models.engine).totals(key_id, datetime.now(UTC))).today
    with isolation.scope("local", None):
        share = (await keys.tenant_share(key_id, "local", Decimal("2"))).spent if per_tenant else charged
    ledgers = {"period totals": today, "key spent": await models.spent(key_id), "tenant share": share}
    assert ledgers == dict.fromkeys(ledgers, charged), f"the ledgers disagree on the {charged} charged: {ledgers}"


async def _ledgers(models: Models, key_id: str, *, per_tenant: bool, charged: Decimal) -> dict[str, Decimal]:
    """Every ledger a call's cost lands in, beside what it should hold when the call was charged once."""
    keys = ModelKeys(models.engine)
    today = (await CallLog(models.engine).totals(key_id, datetime.now(UTC))).today
    with isolation.scope("local", None):
        share = (await keys.tenant_share(key_id, "local", Decimal("2"))).spent if per_tenant else charged
    return {"period totals": today, "key spent": await models.spent(key_id), "tenant share": share}


# A call that names no account is refused before it reaches a provider (400 tenant_required), so only a tenant's call
# is ever billed and lost.
@pytest.mark.parametrize("kind", ["one_budget", "per_tenant"])
async def test_a_charge_both_settle_attempts_lost_is_replayed_once(models: Models, kind: str) -> None:
    """The settle and its fallback both fail after the provider billed: the log carries the whole charge, and its
    replay records it once in every ledger, however many times it runs (the call's id is the row's key)."""
    key_id, secret = await models.key(budget="5")
    if kind == "per_tenant":
        await ModelKeys(models.engine).set_tenant_budget(key_id, Decimal("2"))

    def fail() -> None:
        raise RuntimeError("the database went away")

    remove = _on_spend_write(models, fail)
    try:
        with captured_logging("models-settle-lost") as stream, contextlib.suppress(RuntimeError):
            await models.complete(secret, **{"X-Tenant-Id": "local"})
    finally:
        remove()
    lines = stream.getvalue().splitlines()
    lost = [json.loads(x) for x in lines if x.startswith("{") and '"model_call_row_lost"' in x]
    assert len(lost) == 1 and lost[0]["level"] == "error", "the charge nothing recorded was not logged to replay"
    charged = Decimal(lost[0]["cost"])
    assert charged > 0 and await models.spent(key_id) == 0, lost
    # Whether the key spends per tenant is read from the key, not the line: a line saying otherwise still charges the
    # tenant's share.
    lines = [x.replace('"per_tenant":true', '"per_tenant":false') for x in lines]
    # A key id the log masked (an email in it) names no key: its line is refused, not charged to the masked id.
    masked = [x.replace(key_id, "user:[email]") for x in lines]
    assert await replay_lines(models.engine, masked) == (0, 0, 1)
    assert await replay_lines(models.engine, lines) == (1, 0, 0)
    assert await replay_lines(models.engine, lines) == (0, 1, 0), "a second replay of one call charged it again"
    rows = [(r["outcome"], r["reason"]) for r in await models.calls(key_id)]
    assert rows == [("error", "settle_failed")], rows
    ledgers = await _ledgers(models, key_id, per_tenant=kind == "per_tenant", charged=charged)
    assert ledgers == dict.fromkeys(ledgers, charged), f"the ledgers disagree on the {charged} charged: {ledgers}"


@pytest.mark.postgresql_only("fails the commit at the PostgreSQL driver after the server committed")
async def test_a_fallback_after_a_settle_that_committed_adds_nothing(
    models: Models, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The settle's commit lands but reports a failure (the connection dropped on the reply): its fallback writes the
    same call id, fails on it, and the call stays charged once with its one `ok` row."""
    key_id, secret = await models.key(budget="5")
    dialect = models.engine.sync_engine.dialect
    commit = dialect.do_commit
    armed: list[bool] = []
    lost: list[bool] = []

    def commit_then_drop(dbapi_connection: Any) -> None:
        commit(dbapi_connection)
        if armed and not lost:
            lost.append(True)
            raise RuntimeError("the connection dropped after the commit")

    monkeypatch.setattr(dialect, "do_commit", commit_then_drop)
    remove = _on_spend_write(models, lambda: armed.append(True))
    try:
        with contextlib.suppress(RuntimeError):
            await models.complete(secret, **{"X-Tenant-Id": "local"})
    finally:
        remove()
    assert lost, "the settle's commit never ran"
    rows = await models.calls(key_id)
    assert [(r["outcome"], r["reason"]) for r in rows] == [("ok", None)], rows
    charged = Decimal(rows[0]["cost"])
    ledgers = await _ledgers(models, key_id, per_tenant=False, charged=charged)
    assert ledgers == dict.fromkeys(ledgers, charged), f"the ledgers disagree on the {charged} charged: {ledgers}"


@pytest.mark.postgresql_only("holds PostgreSQL row locks to order the settle and the sweep")
async def test_a_settle_racing_the_spend_sweep_counts_once(models: Models) -> None:
    """The spend sweep deletes a run's row it read as idle while a settle is adding to it: the sweep waits on the
    settle, then keeps the row, so the run's total holds its earlier spend and this call's, each once."""
    key_id, secret = await models.key(budget="5")
    spend, run = KeySpend(models.engine), "run_swept_1"
    now = datetime.now(UTC)
    idle = now - timedelta(seconds=SPEND_KEPT_IDLE_S + 86400)
    await spend.record(key_id, Decimal("0.30"), run, idle, untenanted=None)
    lock = await models.engine.connect()
    await lock.begin()
    # Holds the key's stale rate row, so the settle waits at its delete after it added to the run's row.
    await lock.execute(
        sa.text("UPDATE model_key_spend SET calls = calls WHERE key_id = :k AND period LIKE 'sec:%'"), {"k": key_id}
    )
    waiting: list[bool] = []

    def hook(_c: object, _cur: object, statement: str, *_: object) -> None:
        if statement.lstrip().upper().startswith("DELETE FROM MODEL_KEY_SPEND"):
            waiting.append(True)

    event.listen(models.engine.sync_engine, "before_cursor_execute", hook)
    process = background.BY_KEY[SPEND_SWEEP]
    assert process.sweep is not None
    sweep = process.sweep

    async def sweep_once() -> None:
        async with spend.sweep_tx() as c:
            await sweep(c, datetime.now(UTC).timestamp())

    try:
        call = asyncio.ensure_future(models.complete(secret, **{"X-Tenant-Id": "local", "X-Run-Id": run}))
        for _ in range(250):
            if waiting:
                break
            await asyncio.sleep(0.02)
        assert waiting, "the call never reached its settle"
        swept = asyncio.ensure_future(sweep_once())
        await asyncio.sleep(0.3)
        await lock.rollback()
        assert (await asyncio.wait_for(call, 10)).status_code == 200
        await asyncio.wait_for(swept, 10)
    finally:
        event.remove(models.engine.sync_engine, "before_cursor_execute", hook)
        if lock.in_transaction():
            await lock.rollback()
        await lock.close()
    charged = Decimal((await models.calls(key_id))[0]["cost"])
    total = (await spend.totals(key_id, now, run_id=run)).run
    assert total == Decimal("0.30") + charged, f"the run holds {total}, not its 0.30 and the {charged} charged"
    assert await models.spent(key_id) == charged
