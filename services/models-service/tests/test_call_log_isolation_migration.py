"""Migration models_0012 moves the call log under the tenant policy, by failure mode: a key's caps lose the spend its
log recorded before the move; a call that named no tenant is lost, or stays in the policed log; a re-run of the
backfill doubles a total; the backfill writes spend nobody reads again (a past day, a run idle past the sweep's
window) or drops a long-running run's earlier calls; the down path loses the tenant-less calls. Seeded with two
tenants' calls and refusals, on each database; the seed and the checks read past the tenant policy, as the migration
does."""

from __future__ import annotations

import asyncio
import importlib.util
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import cast
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from ops_models.store.tables import SPEND_KEPT_IDLE_S

from .conftest import past_the_call_log_policy

ROOT = Path(__file__).resolve().parents[1]
BEFORE = "models_0011"
MIGRATION = ROOT / "migrations" / "versions" / "0012_call_log_tenant_isolation.py"


async def _sql(url: str, statements: list[tuple[str, dict[str, object]]]) -> list[list[tuple[object, ...]]]:
    engine = create_async_engine(url)
    out: list[list[tuple[object, ...]]] = []
    async with engine.begin() as c, past_the_call_log_policy(c):
        for text, params in statements:
            result = await c.execute(sa.text(text), params)
            out.append([tuple(r) for r in result.all()] if result.returns_rows else [])
    await engine.dispose()
    return out


INSERT = (
    "INSERT INTO model_call_log (id, key_id, alias, input_tokens, output_tokens, cost, latency_ms, outcome, run_id, "
    "tenant_id, created_at, images) "
    "VALUES (:id, :k, 'bank-standard', 1, 1, :cost, 1, :outcome, :run, :tenant, :at, 0)"
)


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("models_0012", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def module_kept_idle() -> float | None:
    return cast(float | None, getattr(_migration(), "KEPT_IDLE_S", None))


async def _rerun(url: str, statements: list[str]) -> None:
    await _sql(url, [(text, {}) for text in statements])


def test_the_log_moves_under_the_policy_with_its_spend_and_its_refusals_kept(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The chain's env reads the URL from Settings, so Alembic migrates the database this case runs on.
    monkeypatch.setenv("OPS_DATABASE_URL", database_url)
    dialect = make_url(database_url).get_backend_name()
    cfg = Config(str(ROOT / "alembic.ini"))
    key = f"workflow:mig-{uuid4().hex[:8]}"
    now = datetime.now(UTC)
    idle = now - timedelta(seconds=SPEND_KEPT_IDLE_S + 86400)
    seeded = [
        ("t_a", "ok", "0.25", "run_m1", now),
        ("t_b", "ok", "0.50", "run_m1", now),
        ("t_b", "ok", "1.00", None, now),
        (None, "denied", "0", "run_m1", now),
        (None, "denied", "0", None, now),
        # A run that started before the window and is still going keeps its whole total.
        ("t_a", "ok", "0.30", "run_long", idle),
        ("t_a", "ok", "0.10", "run_long", now),
        # A run idle past the window, and a past day, are spend no cap reads again.
        ("t_a", "ok", "0.05", "run_gone", idle),
        ("t_b", "ok", "0.07", None, now - timedelta(days=1)),
    ]
    ids = [f"mc_mig_{uuid4().hex[:10]}" for _ in seeded]
    command.downgrade(cfg, BEFORE)
    try:
        rows: list[tuple[str, dict[str, object]]] = [
            (INSERT, {"id": i, "k": key, "tenant": t, "outcome": o, "cost": Decimal(c), "run": r, "at": at})
            for i, (t, o, c, r, at) in zip(ids, seeded, strict=True)
        ]
        asyncio.run(_sql(database_url, rows))
        command.upgrade(cfg, "head")
        spend_q = (
            "SELECT period, amount, calls, last_call_s FROM model_key_spend "
            "WHERE key_id = :k AND period NOT LIKE 'sec:%' ORDER BY period"
        )
        log_q = "SELECT id FROM model_call_log WHERE key_id = :k AND tenant_id IS NULL"
        kept_q = "SELECT count(*) FROM model_calls_untenanted WHERE key_id = :k"
        day = f"day:{now.date().isoformat()}"
        spend, nulls, kept = asyncio.run(
            _sql(database_url, [(spend_q, {"k": key}), (log_q, {"k": key}), (kept_q, {"k": key})])
        )
        assert [r[:3] for r in spend] == [
            (day, Decimal("1.85"), 6),
            ("run:run_long", Decimal("0.40"), 2),
            ("run:run_m1", Decimal("0.75"), 3),
        ], "the caps lost logged spend, or the backfill wrote spend no cap reads"
        assert all(abs(cast(float, r[3]) - now.timestamp()) < 60 for r in spend), (
            "a row's last call is not its newest call"
        )
        assert module_kept_idle() == SPEND_KEPT_IDLE_S, "the backfill and the sweep keep different windows"
        assert (nulls, kept) == ([], [(2,)]), "a tenant-less call stayed in the policed log or was lost"

        # The backfill sets totals from the log, so a second run changes nothing.
        asyncio.run(_rerun(database_url, _migration().backfill_sql(dialect)))
        assert asyncio.run(_sql(database_url, [(spend_q, {"k": key})]))[0] == spend, "a re-run changed a total"

        command.downgrade(cfg, BEFORE)
        back = "SELECT count(*) FROM model_call_log WHERE key_id = :k AND tenant_id IS NULL"
        tables = (
            # Upper case: SQL Server's binary collation matches catalog names exactly; PostgreSQL folds them.
            "SELECT count(*) FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_NAME IN ('model_key_spend', 'model_calls_untenanted')"
        )
        restored, gone = asyncio.run(_sql(database_url, [(back, {"k": key}), (tables, {})]))
        assert (restored, gone) == ([(2,)], [(0,)]), "the down path lost the tenant-less calls or left a table"
    finally:
        command.upgrade(cfg, "head")
        asyncio.run(_sql(database_url, [("DELETE FROM model_call_log WHERE key_id = :k", {"k": key})]))


def test_a_call_an_old_pod_is_writing_during_the_move_still_counts_toward_the_cap(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The backfill totals a key's spend from the log: a call inserted, not yet committed, when the migration starts
    is counted, because the migration waits for the log's writers before it reads."""
    monkeypatch.setenv("OPS_DATABASE_URL", database_url)
    cfg = Config(str(ROOT / "alembic.ini"))
    key, now = f"workflow:lock-{uuid4().hex[:8]}", datetime.now(UTC)
    row = {"id": f"mc_lk_{uuid4().hex[:10]}", "k": key, "tenant": "t_a", "outcome": "ok", "run": None, "at": now}

    async def race() -> None:
        engine = create_async_engine(database_url)
        async with engine.connect() as c:
            await c.begin()
            async with past_the_call_log_policy(c):
                await c.execute(sa.text(INSERT), {**row, "cost": Decimal("0.40")})
            migrating = asyncio.ensure_future(asyncio.to_thread(command.upgrade, cfg, "head"))
            await asyncio.sleep(1.0)  # the migration has started and reaches the log
            await c.commit()
            await asyncio.wait_for(migrating, 60)
        await engine.dispose()

    command.downgrade(cfg, BEFORE)
    try:
        asyncio.run(race())
        q = "SELECT amount FROM model_key_spend WHERE key_id = :k AND period LIKE 'day:%'"
        assert asyncio.run(_sql(database_url, [(q, {"k": key})]))[0] == [(Decimal("0.4"),)], "the call was missed"
    finally:
        command.upgrade(cfg, "head")
        asyncio.run(_sql(database_url, [("DELETE FROM model_call_log WHERE key_id = :k", {"k": key})]))
