"""Migration 20261127_0900, by failure mode: a batch made before it gets no group key, so the not-null step fails on
upgrade, or two batches of one workflow collide on the group index; the down path cannot run with a waiting file held.
"""

from __future__ import annotations

import asyncio

from alembic import command
from alembic.config import Config

from .test_drop_publish_policies import ROOT, _sql  # pyright: ignore[reportPrivateUsage]

BEFORE = "20261125_1000_check_batches"
BATCH = (
    "INSERT INTO run_batches (id, tenant_id, team_id, workflow_id, version, mode, file_id, file_name, total,"
    " created_by, created_at) VALUES (:id, 't-mig0900', 'team_ap', 'wf_levy', 1, 'live', 'fil_1', 'levies.csv', 0,"
    " 'b', 'n')"
)
READ = "SELECT id, group_key, part FROM run_batches WHERE tenant_id = 't-mig0900' ORDER BY id"
HOLD = (
    "INSERT INTO batch_waiting_files (tenant_id, workflow_id, item_key, team_id, group_key, group_name, input,"
    " held_at) VALUES ('t-mig0900', 'wf_levy', 'k1', 'team_ap', 'g1', 'Batch001', '{}', 'n')"
)


def test_batches_before_it_are_each_their_own_group_and_a_held_file_does_not_stop_the_down_path(
    emptied_database: str,
) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    for _ in range(2):
        command.downgrade(cfg, BEFORE)
        asyncio.run(
            _sql(
                emptied_database,
                ("DELETE FROM run_batches WHERE tenant_id = 't-mig0900'", {}),
                (BATCH, {"id": "batch_g1"}),
                (BATCH, {"id": "batch_g2"}),
            )
        )
        command.upgrade(cfg, "head")
        (read,) = asyncio.run(_sql(emptied_database, (READ, {})))
        assert read == [("batch_g1", "batch_g1", 1), ("batch_g2", "batch_g2", 1)]
        asyncio.run(
            _sql(emptied_database, ("DELETE FROM batch_waiting_files WHERE tenant_id = 't-mig0900'", {}), (HOLD, {}))
        )
