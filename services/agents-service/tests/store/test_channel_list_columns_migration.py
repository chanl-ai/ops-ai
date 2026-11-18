"""Migration 0118, by failure mode: the API key copy without its row policy holds every tenant's keys for any reader;
a version stored before it lists no mailbox, so its mailbox shows as watched by nothing; the down path leaves a
database 0117 runs on; the upgrade cannot run again."""

from __future__ import annotations

import asyncio
import json

from alembic import command
from alembic.config import Config

from .test_drop_publish_policies import ROOT, _sql  # pyright: ignore[reportPrivateUsage]

BEFORE = "0117_validation_list_columns"
POLICIES = "SELECT tablename, policyname FROM pg_policies WHERE tablename = 'api_key_copies'"
HELD = "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'api_key_copies'"
COLUMN = (
    "SELECT column_name FROM information_schema.columns"
    " WHERE table_name = 'engine_definitions' AND column_name = 'mailbox'"
)
DEFINITION = {"nodes": [{"id": "t", "type": "ops.trigger.email", "parameters": {"mailbox": "ops@bank.example"}}]}
SEED = (
    "INSERT INTO engine_definitions (tenant_id, workflow_id, version, digest, name, definition, created_at, created_by,"
    " stage, description, trigger, startable, takes_files) VALUES (:t, :w, 1, :w, 'Intake', :d, 'n', 'b', 'live', '',"
    " '', false, false)"
)
READ = "SELECT workflow_id, mailbox FROM engine_definitions WHERE tenant_id = 't-mig118' ORDER BY workflow_id"


def test_the_copy_is_policed_and_old_versions_name_their_mailbox_down_and_up_again(emptied_database: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    for _ in range(2):
        command.downgrade(cfg, BEFORE)
        assert asyncio.run(_sql(emptied_database, (POLICIES, {}), (HELD, {}), (COLUMN, {}))) == [[], [], []]
        asyncio.run(
            _sql(
                emptied_database,
                ("DELETE FROM engine_definitions WHERE tenant_id = 't-mig118'", {}),
                (SEED, {"t": "t-mig118", "w": "wf_mail", "d": json.dumps(DEFINITION)}),
                (SEED, {"t": "t-mig118", "w": "wf_none", "d": json.dumps({"nodes": []})}),
            )
        )
        command.upgrade(cfg, "head")
        policies, held, read = asyncio.run(_sql(emptied_database, (POLICIES, {}), (HELD, {}), (READ, {})))
        assert policies == [("api_key_copies", "api_key_copies_isolation")]
        assert held == [("api_key_copies", True, True)]
        assert read == [("wf_mail", "ops@bank.example"), ("wf_none", None)]
