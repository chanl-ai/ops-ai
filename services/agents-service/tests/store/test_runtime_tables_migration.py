"""Migration 0104 gives each budget and recorded model call its thread's tenant, by failure mode: a row whose thread is
gone was deleted, losing recorded spend the down path could not bring back; such a row kept the dev tenant `local`, so
a caller in a tenant of that name read other tenants' recorded responses; a gone thread's events, which still name its
tenant, were not read; the column kept a `local` default, so a write that named no tenant landed there too, and older
tables kept the same default (0114); a backfill larger than one batch left rows unfilled; a run stopped after the
column was added could not be run again; the down path left a database 0103 could not run on."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.store.tenancy import TENANT_ROLE
from ops_service_kit.ids import new_id, now_iso

from .test_drop_publish_policies import ROOT, _sql  # pyright: ignore[reportPrivateUsage]

BEFORE = "0103_eval_cases_runs"
# One more than a batch (BATCH in 0104), so the backfill has to loop.
MANY = 5001
THREAD = (
    "INSERT INTO graph_threads (tenant_id, id, graph, meta, team_id, created_at, updated_at, status) "
    "VALUES (:t, :id, 'chat', CAST('{}' AS json), :team, :at, :at, 'idle')"
)
EVENT = (
    "INSERT INTO thread_events (id, thread_id, seq, type, at, team_id, tenant_id) "
    "VALUES (:e, :id, :seq, 'run.started', :at, 'team_x', :t)"
)
BUDGET = "INSERT INTO thread_budgets (thread_id, max_calls, updated_at) VALUES (:id, 3, :at)"
CALLS = (
    "INSERT INTO model_call_records (id, thread_id, step, kind, model_alias, calls, input_tokens, output_tokens, "
    "cost_micros, created_at) SELECT :p || n, :id, 's', 'chat', 'm', 1, 1, 1, :c, :at FROM generate_series(1, :n) n"
)
# Each thread's budgets and calls and the calls' summed cost, in the two tables, and with their side tables after 0104.
CALLS_IN = "SELECT COUNT(*), SUM(cost_micros) FROM model_call_records WHERE thread_id IN (:a, :b, :c)"
BUDGETS_IN = "SELECT COUNT(*) FROM thread_budgets WHERE thread_id IN (:a, :b, :c)"
CALLS_KEPT = (
    "SELECT COUNT(*), SUM(cost_micros) FROM (SELECT cost_micros FROM model_call_records "
    "WHERE thread_id IN (:a, :b, :c) "
    "UNION ALL SELECT cost_micros FROM model_call_records_unattributed WHERE thread_id IN (:a, :b, :c)) k"
)
BUDGETS_KEPT = (
    "SELECT COUNT(*) FROM (SELECT thread_id FROM thread_budgets WHERE thread_id IN (:a, :b, :c) "
    "UNION ALL SELECT thread_id FROM thread_budgets_unattributed WHERE thread_id IN (:a, :b, :c)) k"
)
SIDE_READS = (
    "SELECT COUNT(*) FROM model_call_records_unattributed",
    "SELECT COUNT(*) FROM thread_budgets_unattributed",
)
CLEAN = (
    "DELETE FROM model_call_records WHERE thread_id IN (:a, :b, :c)",
    "DELETE FROM thread_budgets WHERE thread_id IN (:a, :b, :c)",
    "DELETE FROM model_call_records_unattributed WHERE thread_id IN (:a, :b, :c)",
    "DELETE FROM thread_budgets_unattributed WHERE thread_id IN (:a, :b, :c)",
    "DELETE FROM thread_events WHERE thread_id IN (:a, :b, :c)",
    "DELETE FROM graph_threads WHERE id = :a",
)


def _totals(url: str, threads: list[str], *, side: bool) -> list[Any]:
    """Every budget and call of `threads` and the calls' summed cost, with the side tables once 0104 has run."""
    ids = dict(zip("abc", threads, strict=True))
    return asyncio.run(_sql(url, (CALLS_KEPT if side else CALLS_IN, ids), (BUDGETS_KEPT if side else BUDGETS_IN, ids)))


async def _as_tenant(url: str, tenant: str, statement: str, params: dict[str, Any]) -> list[Any]:
    """`statement` in a transaction as the runtime tenant role, holding `tenant`: what a tenant's raw SQL reads."""
    engine = create_async_engine(url)
    try:
        async with engine.begin() as c:
            await c.execute(sa.text(f"SET LOCAL ROLE {TENANT_ROLE}"))
            await c.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant})
            return list((await c.execute(sa.text(statement), params)).all())
    finally:
        await engine.dispose()


def test_every_row_is_kept_held_to_its_tenant_or_to_no_tenant_and_no_default_remains(emptied_database: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, BEFORE)
    tenant, thread, at = new_id("ten"), new_id("gth"), now_iso()
    # A thread gone with nothing else naming it, and one gone whose events still name its tenant (and `local`).
    gone, evented, owner = new_id("wft"), new_id("wft"), new_id("ten")
    threads = [thread, gone, evented]
    asyncio.run(
        _sql(
            emptied_database,
            # A run stopped after the column was added: the upgrade runs again over it.
            ("ALTER TABLE thread_budgets ADD COLUMN tenant_id VARCHAR(64)", {}),
            (THREAD, {"t": tenant, "id": thread, "team": new_id("team"), "at": at}),
            (EVENT, {"e": new_id("ev"), "id": evented, "seq": 1, "at": at, "t": owner}),
            (EVENT, {"e": new_id("ev"), "id": evented, "seq": 2, "at": at, "t": "local"}),
            *((BUDGET, {"id": t, "at": at}) for t in threads),
            (CALLS, {"p": f"{thread}_", "id": thread, "at": at, "n": MANY, "c": 1}),
            (CALLS, {"p": f"{gone}_", "id": gone, "at": at, "n": 2, "c": 700}),
            (CALLS, {"p": f"{evented}_", "id": evented, "at": at, "n": 3, "c": 50}),
        )
    )
    seeded = _totals(emptied_database, threads, side=False)
    assert seeded == [[(MANY + 5, MANY + 1400 + 150)], [(3,)]]
    command.upgrade(cfg, "head")
    assert _totals(emptied_database, threads, side=True) == seeded
    budgets, calls = asyncio.run(
        _sql(
            emptied_database,
            ("SELECT thread_id, tenant_id FROM thread_budgets ORDER BY tenant_id", {}),
            ("SELECT thread_id, tenant_id, COUNT(*) FROM model_call_records GROUP BY thread_id, tenant_id", {}),
        )
    )
    assert sorted(budgets) == sorted([(thread, tenant), (evented, owner)])
    assert sorted(calls) == sorted([(thread, tenant, MANY), (evented, owner, 3)])
    # Each tenant reads only its own rows; the rows no tenant can be named for are read by no tenant context.
    mine = "SELECT thread_id, COUNT(*) FROM model_call_records GROUP BY thread_id"
    assert asyncio.run(_as_tenant(emptied_database, owner, mine, {})) == [(evented, 3)]
    assert asyncio.run(_as_tenant(emptied_database, "local", mine, {})) == []
    for read in SIDE_READS:
        for who in (tenant, owner, "local"):
            with pytest.raises(ProgrammingError, match="permission denied"):
                asyncio.run(_as_tenant(emptied_database, who, read, {}))
    with pytest.raises(IntegrityError):
        asyncio.run(_sql(emptied_database, (BUDGET, {"id": new_id("gth"), "at": at})))
    # Nor does any older table's tenant_id keep the `local` default (0114).
    (defaulted,) = asyncio.run(
        _sql(
            emptied_database,
            (
                "SELECT table_name FROM information_schema.columns WHERE column_name = 'tenant_id' "
                "AND column_default LIKE '%local%' ORDER BY table_name",
                {},
            ),
        )
    )
    assert defaulted == []
    # Down brings every row back to the tables; up again holds the same rows the same way.
    command.downgrade(cfg, BEFORE)
    assert _totals(emptied_database, threads, side=False) == seeded
    command.upgrade(cfg, "head")
    assert _totals(emptied_database, threads, side=True) == seeded
    # Its own rows, removed after, so no later migration's check reads them.
    ids = {"a": thread, "b": gone, "c": evented}
    asyncio.run(_sql(emptied_database, *((statement, ids) for statement in CLEAN)))


def test_0119_makes_the_side_tables_an_earlier_0104_left_out_and_leaves_ones_there(emptied_database: str) -> None:
    """A database that ran 0104 before it made its side tables gets them from 0119; a run again and the down path keep
    them, and a row in one survives."""
    cfg = Config(str(ROOT / "alembic.ini"))
    sides = ("thread_budgets_unattributed", "model_call_records_unattributed")
    command.downgrade(cfg, "0118_channel_list_columns")
    drops: list[tuple[str, dict[str, Any]]] = [(f"DROP TABLE {t}", {}) for t in sides]
    asyncio.run(_sql(emptied_database, *drops))
    command.upgrade(cfg, "head")
    kept = "INSERT INTO thread_budgets_unattributed (thread_id, updated_at) VALUES ('th_gone', 'then')"
    asyncio.run(_sql(emptied_database, (kept, {})))
    command.downgrade(cfg, "0118_channel_list_columns")
    command.upgrade(cfg, "head")
    count = "SELECT COUNT(*) FROM thread_budgets_unattributed"
    found = asyncio.run(
        _sql(emptied_database, (count, {}), ("SELECT COUNT(*) FROM model_call_records_unattributed", {}))
    )
    assert found == [[(1,)], [(0,)]]
    asyncio.run(_sql(emptied_database, ("DELETE FROM thread_budgets_unattributed", {})))


def test_skill_pins_dropped_by_the_down_path_come_back_from_the_newest_version(emptied_database: str) -> None:
    """agent_skill_pins copies the newest version's spec.skillPins: down past 0113 and up again, every row is back."""
    cfg = Config(str(ROOT / "alembic.ini"))
    at, tenant = now_iso(), new_id("ten")
    old = '{"skillPins": [{"skillId": "skl_gone", "version": 1}]}'
    new = '{"skillPins": [{"skillId": "skl_a", "version": 3}, {"skillId": "skl_b", "version": 1}, "bad"]}'
    version = (
        "INSERT INTO registry_agent_versions (tenant_id, agent_id, version, spec, digest, note, changes, saved_at, "
        "saved_by) VALUES (:t, 'agt_pins', :v, CAST(:s AS json), :d, '', CAST('[]' AS json), :at, 'p')"
    )
    pins = "SELECT agent_id, skill_id, version, team_id FROM agent_skill_pins ORDER BY skill_id"
    asyncio.run(
        _sql(
            emptied_database,
            (
                "INSERT INTO registry_agents (tenant_id, id, slug, team_id, version, paused, created_at, updated_at) "
                "VALUES (:t, 'agt_pins', 'pins', 'team_a', 2, false, :at, :at)",
                {"t": tenant, "at": at},
            ),
            (version, {"t": tenant, "v": 1, "d": "d1", "s": old, "at": at}),
            (version, {"t": tenant, "v": 2, "d": "d2", "s": new, "at": at}),
            (
                "INSERT INTO agent_skill_pins (tenant_id, team_id, agent_id, skill_id, version) VALUES "
                "(:t, 'team_a', 'agt_pins', 'skl_a', 3), (:t, 'team_a', 'agt_pins', 'skl_b', 1)",
                {"t": tenant},
            ),
        )
    )
    (before,) = asyncio.run(_sql(emptied_database, (pins, {})))
    command.downgrade(cfg, "0112_definitions_list_indexes")
    command.upgrade(cfg, "head")
    (after,) = asyncio.run(_sql(emptied_database, (pins, {})))
    assert after == before == [("agt_pins", "skl_a", 3, "team_a"), ("agt_pins", "skl_b", 1, "team_a")]
    asyncio.run(_sql(emptied_database, ("DELETE FROM registry_agents WHERE id = 'agt_pins'", {})))
