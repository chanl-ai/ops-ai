"""Migration 20261125_1000, by failure mode: a 1.1.0 spreadsheet batch's rows get no workflow or item key, so the
not-null step fails on upgrade; the down path cannot run with a check batch present."""

from __future__ import annotations

import asyncio

from alembic import command
from alembic.config import Config

from .test_drop_publish_policies import ROOT, _sql  # pyright: ignore[reportPrivateUsage]

BEFORE = "20261124_0257_skill_owner_ids"
BATCH = (
    "INSERT INTO run_batches (id, tenant_id, team_id, workflow_id, version, mode, file_id, file_name, total,"
    " created_by, created_at) VALUES ('batch_m1', 't-mig1000', 'team_ap', 'wf_levy', 1, 'live', 'fil_1',"
    " 'levies.csv', 2, 'b', 'n')"
)
ROW = (
    'INSERT INTO run_batch_rows (tenant_id, batch_id, "row", team_id, input)'
    " VALUES ('t-mig1000', 'batch_m1', :r, 'team_ap', '{}')"
)
READ = 'SELECT "row", workflow_id, item_key FROM run_batch_rows WHERE tenant_id = \'t-mig1000\' ORDER BY "row"'
CHECK = (
    "INSERT INTO run_batches (id, tenant_id, team_id, workflow_id, version, mode, origin, file_name, watch_id, total,"
    " created_by, created_at, group_key) VALUES ('batch_c1', 't-mig1000', 'team_ap', 'wf_levy', 1, 'live', 'check',"
    " 'x', 'wat_1', 0, 'b', 'n', 'batch_c1')"
)


def test_a_spreadsheet_batch_is_backfilled_and_a_check_batch_does_not_stop_the_down_path(
    emptied_database: str,
) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    for _ in range(2):
        command.downgrade(cfg, BEFORE)
        asyncio.run(
            _sql(
                emptied_database,
                ("DELETE FROM run_batch_rows WHERE tenant_id = 't-mig1000'", {}),
                ("DELETE FROM run_batches WHERE tenant_id = 't-mig1000'", {}),
                (BATCH, {}),
                (ROW, {"r": 1}),
                (ROW, {"r": 2}),
            )
        )
        command.upgrade(cfg, "head")
        (read,) = asyncio.run(_sql(emptied_database, (READ, {})))
        assert read == [(1, "wf_levy", "batch_m1:1"), (2, "wf_levy", "batch_m1:2")]
        asyncio.run(_sql(emptied_database, (CHECK, {})))
