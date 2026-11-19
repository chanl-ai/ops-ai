"""Migration 0115 works out each v2 definition version's Workflows list columns, by failure mode: a version stored
before it has no description, trigger or start to search and filter on, so the list leaves it out of Start run and
Files or lists it with nothing; a fill larger than one batch, over two tenants, leaves versions empty or never ends; the
down path leaves a database 0114 runs on and the upgrade runs again."""

from __future__ import annotations

import asyncio
import json

from alembic import command
from alembic.config import Config

from ops_service_kit.ids import new_id, now_iso

from .test_drop_publish_policies import ROOT, _sql  # pyright: ignore[reportPrivateUsage]

BEFORE = "0114_drop_local_tenant_defaults"
ROW = (
    "INSERT INTO engine_definitions (tenant_id, workflow_id, version, digest, name, definition, created_at, "
    "created_by, stage) VALUES (:t, :w, 1, :w, :w, CAST(:d AS json), :at, 'a@x', 'draft')"
)


def _trigger(kind: str, description: str = "") -> str:
    return json.dumps({"description": description, "nodes": [{"id": "start", "type": kind, "typeVersion": 1}]})


def test_versions_stored_before_gain_their_list_columns_and_the_down_path_runs(emptied_database: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, BEFORE)
    tenant, other, at = new_id("ten"), new_id("ten"), now_iso()
    rows = {
        "wf_email": _trigger("ops.trigger.email"),
        "wf_request": _trigger("ops.trigger.request", "Opened from the portal"),
        "wf_none": json.dumps({"nodes": []}),
    }
    asyncio.run(
        _sql(
            emptied_database,
            *((ROW, {"t": tenant, "w": w, "d": d, "at": at}) for w, d in rows.items()),
            # One more than a batch (BATCH in 0115), half in another tenant.
            (
                "INSERT INTO engine_definitions (tenant_id, workflow_id, version, digest, name, definition, "
                "created_at, created_by, stage) SELECT CASE WHEN n % 2 = 0 THEN :t ELSE :o END, 'wf_many_' || n, 1, "
                "'wf_many_' || n, 'Many', CAST(:d AS json), :at, 'a@x', 'draft' FROM generate_series(1, 1001) n",
                {"t": tenant, "o": other, "d": _trigger("ops.trigger.schedule"), "at": at},
            ),
        )
    )
    command.upgrade(cfg, "head")
    listed = 'SELECT workflow_id, description, "trigger", startable, takes_files FROM engine_definitions '
    found, many = asyncio.run(
        _sql(
            emptied_database,
            (listed + "WHERE tenant_id = :t AND workflow_id NOT LIKE 'wf_many_%'", {"t": tenant}),
            (
                'SELECT "trigger", startable, takes_files, COUNT(*) FROM engine_definitions '
                "WHERE workflow_id LIKE 'wf_many_%' GROUP BY \"trigger\", startable, takes_files",
                {},
            ),
        )
    )
    assert sorted(found) == [
        ("wf_email", "", "Email received", True, True),
        ("wf_none", "", "", False, False),
        ("wf_request", "Opened from the portal", "Opened from the portal", True, False),
    ]
    assert many == [("Schedule", True, False, 1001)]
    command.downgrade(cfg, BEFORE)
    command.upgrade(cfg, "head")
    asyncio.run(
        _sql(
            emptied_database,
            ("DELETE FROM engine_definitions WHERE tenant_id IN (:t, :o)", {"t": tenant, "o": other}),
        )
    )
