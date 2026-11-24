"""The revision that resets stored self-approval to Admin only (owner, 23 November), by failure mode: a team that
turned self-approval on keeps it; a tenant that stored nothing reads 1.1.0's default (on) after a rollback; a reset
leaves no audit row; a second run writes again. Runs the real chain on the test database."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Any

from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from ops_access import requester_may_decide
from ops_service_kit.ids import new_id, now_iso

from .conftest import alembic_config
from .test_self_approval_migration import _run  # pyright: ignore[reportPrivateUsage]

REVISION = "20261124_0900_self_approve_reset"
BEFORE = "20261123_1200_self_approval_cell"


def _value(raw: Any) -> Any:
    return json.loads(raw) if isinstance(raw, str) else raw


def _state(url: str, tenants: list[str]) -> tuple[dict[str, Any], dict[str, Any], list[tuple[str, str | None]]]:
    rows, floors, audit = asyncio.run(
        _run(
            url,
            [
                ("SELECT tenant_id, value FROM policies WHERE key = 'requesterMayDecide'", {}),
                ("SELECT tenant_id, value FROM policies WHERE key = 'approvalsFloor'", {}),
                (
                    "SELECT tenant_id, detail FROM audit_entries WHERE actor = :a AND target_id = 'requesterMayDecide'",
                    {"a": f"migration:{REVISION}"},
                ),
            ],
        )
    )
    return (
        {t: _value(v) for t, v in rows if t in tenants},
        {t: _value(v) for t, v in floors if t in tenants},
        sorted(((t, _value(d)["team"]) for t, d in audit if t in tenants), key=str),
    )


def _again(url: str) -> None:
    path = Path(__file__).resolve().parents[1] / f"migrations/versions/{REVISION}.py"
    spec = importlib.util.spec_from_file_location(REVISION, path)
    assert spec and spec.loader
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)

    async def go() -> None:
        engine = create_async_engine(url)
        async with engine.begin() as c:
            await c.run_sync(revision.reset)
        await engine.dispose()

    asyncio.run(go())


def test_every_team_reads_admin_only_after_the_revision_with_one_audit_row_per_reset(database_url: str) -> None:
    stored, empty, now = new_id("ten"), new_id("ten"), now_iso()
    command.downgrade(alembic_config(), BEFORE)
    try:
        writes: list[tuple[str, dict[str, Any]]] = []
        for t in (stored, empty):
            writes.append(
                (
                    "INSERT INTO tenants (id, name, status, allowed_domains, created_at) "
                    "VALUES (:t, :t, 'active', '[]', :now)",
                    {"t": t, "now": now},
                )
            )
        for key, value in (
            ("requesterMayDecide", {"lending": True, "claims": {"reviews": True}}),
            ("approvalsFloor", {"requesterMayDecide": False, "appChanges": "reviewer"}),
        ):
            writes.append(
                (
                    "INSERT INTO policies (tenant_id, key, value, updated_by, updated_at) "
                    "VALUES (:t, :k, :v, 'dana@lending.test', :now)",
                    {"t": stored, "k": key, "v": json.dumps(value), "now": now},
                )
            )
        asyncio.run(_run(database_url, writes))
    finally:
        command.upgrade(alembic_config(), "head")
    values, floors, audit = _state(database_url, [stored, empty])
    # Read as a 1.1.0 tools-service reads it: a team that stored on, one per area, and one that stored nothing.
    for tenant, team in ((stored, "lending"), (stored, "claims"), (stored, "outage"), (empty, "outage")):
        assert requester_may_decide(values[tenant], team, "reviews", floors.get(tenant)) is False, (tenant, team)
    assert floors[stored] == {"appChanges": "reviewer"}
    # One row per team that stored a value, one per tenant default.
    assert audit == sorted([(stored, "lending"), (stored, "claims"), (stored, None), (empty, None)], key=str)
    _again(database_url)
    assert _state(database_url, [stored, empty]) == (values, floors, audit)
