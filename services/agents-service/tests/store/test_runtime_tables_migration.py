"""Migration 0104 gives each budget and recorded model call its thread's tenant, by failure mode: a row whose thread is
gone kept the dev tenant `local`, so a caller in a tenant of that name read other tenants' recorded responses; the
column kept a `local` default, so a write that named no tenant landed there too, and older tables kept the same
default (0114); a backfill larger than one batch left rows unfilled; a run stopped after the column was added could
not be run again; the down path left a database 0103 could not run on."""

from __future__ import annotations

import asyncio

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from ops_service_kit.ids import new_id, now_iso

from .test_drop_publish_policies import ROOT, _sql  # pyright: ignore[reportPrivateUsage]

BEFORE = "0103_eval_cases_runs"
# One more than a batch (BATCH in 0104), so the backfill has to loop.
MANY = 5001
THREAD = (
    "INSERT INTO graph_threads (tenant_id, id, graph, meta, team_id, created_at, updated_at, status) "
    "VALUES (:t, :id, 'chat', CAST('{}' AS json), :team, :at, :at, 'idle')"
)
BUDGET = "INSERT INTO thread_budgets (thread_id, max_calls, updated_at) VALUES (:id, 3, :at)"
CALLS = (
    "INSERT INTO model_call_records (id, thread_id, step, kind, model_alias, calls, input_tokens, output_tokens, "
    "cost_micros, created_at) SELECT :p || n, :id, 's', 'chat', 'm', 1, 1, 1, 1, :at FROM generate_series(1, :n) n"
)


def test_rows_take_their_threads_tenant_orphans_go_and_no_default_remains(emptied_database: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, BEFORE)
    tenant, thread, gone, at = new_id("ten"), new_id("gth"), new_id("wft"), now_iso()
    asyncio.run(
        _sql(
            emptied_database,
            # A run stopped after the column was added: the upgrade runs again over it.
            ("ALTER TABLE thread_budgets ADD COLUMN tenant_id VARCHAR(64)", {}),
            (THREAD, {"t": tenant, "id": thread, "team": new_id("team"), "at": at}),
            (BUDGET, {"id": thread, "at": at}),
            (BUDGET, {"id": gone, "at": at}),
            (CALLS, {"p": f"{thread}_", "id": thread, "at": at, "n": MANY}),
            (CALLS, {"p": f"{gone}_", "id": gone, "at": at, "n": 2}),
        )
    )
    command.upgrade(cfg, "head")
    budgets, calls = asyncio.run(
        _sql(
            emptied_database,
            ("SELECT thread_id, tenant_id FROM thread_budgets WHERE thread_id IN (:a, :b)", {"a": thread, "b": gone}),
            (
                "SELECT thread_id, tenant_id, COUNT(*) FROM model_call_records WHERE thread_id IN (:a, :b) "
                "GROUP BY thread_id, tenant_id",
                {"a": thread, "b": gone},
            ),
        )
    )
    assert budgets == [(thread, tenant)]
    assert calls == [(thread, tenant, MANY)]
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
    command.downgrade(cfg, BEFORE)
    command.upgrade(cfg, "head")
    # Its own rows, removed after, so no later migration's check reads them.
    asyncio.run(
        _sql(
            emptied_database,
            ("DELETE FROM model_call_records WHERE thread_id = :id", {"id": thread}),
            ("DELETE FROM thread_budgets WHERE thread_id = :id", {"id": thread}),
            ("DELETE FROM graph_threads WHERE id = :id", {"id": thread}),
        )
    )
