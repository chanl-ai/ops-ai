"""The revision that resets stored self-approval to Admin only (owner, 23 November), by failure mode: a team that
turned self-approval on keeps it; a tenant that stored nothing reads 1.1.0's default (on) after a rollback; a reset
leaves no audit row; a second run writes again; on SQL Server, a migration that sees no tenant resets nothing. Runs
the real chain on each test database, rows written and read in their tenant's context and the chain run with none."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from ops_access import requester_may_decide
from ops_service_kit.ids import new_id, now_iso

from .conftest import alembic_config
from .test_self_approval_migration import _run  # pyright: ignore[reportPrivateUsage]

REVISION = "20261124_0900_self_approve_reset"
BEFORE = "20261123_1200_self_approval_cell"
# `key` is reserved in T-SQL, so the column is named through SQLAlchemy, which quotes it.
policies = sa.table(
    "policies",
    sa.column("tenant_id", sa.String),
    sa.column("key", sa.String),
    sa.column("value", sa.JSON),
    sa.column("updated_by", sa.String),
    sa.column("updated_at", sa.String),
)
audit = sa.table(
    "audit_entries",
    sa.column("tenant_id", sa.String),
    sa.column("actor", sa.String),
    sa.column("target_id", sa.String),
    sa.column("detail", sa.JSON),
)


def _value(raw: Any) -> Any:
    return json.loads(raw) if isinstance(raw, str) else raw


def _state(url: str, tenants: list[str]) -> tuple[dict[str, Any], dict[str, Any], list[tuple[str, str | None]]]:
    values: dict[str, Any] = {}
    floors: dict[str, Any] = {}
    entries: list[tuple[str, str | None]] = []
    for tenant in tenants:
        rows, floor, written = asyncio.run(
            _run(
                url,
                tenant,
                [
                    (
                        sa.select(policies.c.value).where(
                            policies.c.tenant_id == tenant, policies.c.key == "requesterMayDecide"
                        ),
                        {},
                    ),
                    (
                        sa.select(policies.c.value).where(
                            policies.c.tenant_id == tenant, policies.c.key == "approvalsFloor"
                        ),
                        {},
                    ),
                    (
                        sa.select(audit.c.detail).where(
                            audit.c.tenant_id == tenant,
                            audit.c.actor == f"migration:{REVISION}",
                            audit.c.target_id == "requesterMayDecide",
                        ),
                        {},
                    ),
                ],
            )
        )
        # At most one row per tenant and key (the primary key).
        values.update((tenant, _value(v)) for (v,) in rows)
        floors.update((tenant, _value(v)) for (v,) in floor)
        entries += [(tenant, _value(d)["team"]) for (d,) in written]
    return values, floors, sorted(entries, key=str)


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


def test_every_team_reads_admin_only_after_the_revision_with_one_audit_row_per_reset(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The chain runs where the rows are: env.py reads the URL from Settings.
    monkeypatch.setenv("OPS_DATABASE_URL", database_url)
    stored, empty, now = new_id("ten"), new_id("ten"), now_iso()
    command.downgrade(alembic_config(), BEFORE)
    try:
        for t in (stored, empty):
            writes: list[tuple[Any, dict[str, Any]]] = [
                (
                    "INSERT INTO tenants (id, name, status, allowed_domains, created_at) "
                    "VALUES (:t, :t, 'active', '[]', :now)",
                    {"t": t, "now": now},
                )
            ]
            if t == stored:
                writes += [
                    (
                        policies.insert().values(
                            tenant_id=t, key=key, value=value, updated_by="dana@lending.test", updated_at=now
                        ),
                        {},
                    )
                    for key, value in (
                        ("requesterMayDecide", {"lending": True, "claims": {"reviews": True}}),
                        ("approvalsFloor", {"requesterMayDecide": False, "appChanges": "reviewer"}),
                    )
                ]
            asyncio.run(_run(database_url, t, writes))
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
