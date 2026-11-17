"""Migration 0105 copies a thread's owner out of its meta JSON into its own column, by failure mode: a thread written
before keeps its owner only in the JSON, so a list by owner misses it; a thread with no owner gains one; a fill larger
than one batch, over two tenants, leaves threads without their owner or never ends; a run stopped after the column was
added cannot run again; the down path leaves a database 0104 can run on."""

from __future__ import annotations

import asyncio
import json

from alembic import command
from alembic.config import Config

from ops_service_kit.ids import new_id, now_iso

from .test_drop_publish_policies import ROOT, _sql  # pyright: ignore[reportPrivateUsage]

BEFORE = "0104_runtime_tables_isolated"
ROW = (
    "INSERT INTO graph_threads (tenant_id, id, graph, meta, team_id, created_at, updated_at, status) "
    "VALUES (:t, :id, 'chat', CAST(:m AS json), :team, :at, :at, 'idle')"
)


def test_a_thread_written_before_has_its_owner_in_the_column_and_the_down_path_runs(emptied_database: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, BEFORE)
    tenant, team, owned, unowned = new_id("ten"), new_id("team"), new_id("thr"), new_id("thr")
    at = now_iso()
    asyncio.run(
        _sql(
            emptied_database,
            (
                ROW,
                {
                    "t": tenant,
                    "id": owned,
                    "m": json.dumps({"ownerEmail": "maya@harborpine.example"}),
                    "at": at,
                    "team": team,
                },
            ),
            (ROW, {"t": tenant, "id": unowned, "m": json.dumps({"owner": "Ops Assistant"}), "at": at, "team": team}),
        )
    )
    # One more owned thread than a batch (BATCH in 0105), half in another tenant, and a run stopped after the column
    # was added.
    other = new_id("ten")
    asyncio.run(
        _sql(
            emptied_database,
            (
                "INSERT INTO graph_threads (tenant_id, id, graph, meta, team_id, created_at, updated_at, status) "
                "SELECT CASE WHEN n % 2 = 0 THEN :t ELSE :o END, 'thr_many_' || n, 'chat', "
                "CAST('{\"ownerEmail\": \"ana@harborpine.example\"}' AS json), :team, :at, :at, 'idle' "
                "FROM generate_series(1, 4001) n",
                {"t": tenant, "o": other, "team": team, "at": at},
            ),
            ("ALTER TABLE graph_threads ADD COLUMN owner VARCHAR(320)", {}),
        )
    )
    command.upgrade(cfg, "head")
    (rows,) = asyncio.run(
        _sql(
            emptied_database,
            ("SELECT id, owner FROM graph_threads WHERE tenant_id = :t AND id NOT LIKE 'thr_many_%'", {"t": tenant}),
        )
    )
    assert dict(rows) == {owned: "maya@harborpine.example", unowned: None}
    (many,) = asyncio.run(
        _sql(
            emptied_database,
            ("SELECT owner, COUNT(*) FROM graph_threads WHERE id LIKE 'thr_many_%' GROUP BY owner", {}),
        )
    )
    assert many == [("ana@harborpine.example", 4001)]
    command.downgrade(cfg, BEFORE)
    command.upgrade(cfg, "head")
    # Its own tenant and team, removed after, so no later migration's check reads them.
    asyncio.run(
        _sql(emptied_database, ("DELETE FROM graph_threads WHERE tenant_id IN (:t, :o)", {"t": tenant, "o": other}))
    )
