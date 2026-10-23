"""Migration 0074 (c-507) gives every task and case type one team, by failure mode: a team with work loses a type it
read (its copy is missing, or lacks a version a task pinned); a type with no team survives, so another team's row is
still read; a team's own type is touched; the downgrade cannot run back."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.ids import new_id, now_iso

ROOT = Path(__file__).resolve().parents[2]
BEFORE = "0073_run_tables_team"


async def _sql(url: str, *statements: tuple[str, dict[str, Any]]) -> list[Any]:
    engine = create_async_engine(url)
    out: list[Any] = []
    async with engine.begin() as c:
        await c.execute(sa.text("SET LOCAL row_security = off"))
        for text, params in statements:
            r = await c.execute(sa.text(text), params)
            out.append(r.all() if r.returns_rows else None)
    await engine.dispose()
    return out


HEAD = (
    "INSERT INTO task_types (tenant_id, id, team_id, origin, name, description, version, published_version, "
    "created_at, created_by, updated_at, updated_by) VALUES (:t, :id, :team, :origin, :id, '', 2, 2, :at, 'seed', :at, "
    "'seed')"
)
VERSION = (
    "INSERT INTO task_type_versions (tenant_id, type_id, version, record, saved_at, saved_by, published_at, "
    "published_by) VALUES (:t, :id, :v, CAST(:r AS json), :at, 'seed', :at, 'seed')"
)
CASE = (
    "INSERT INTO cases (id, tenant_id, team_id, subject, status, priority, response_due_at, resolution_due_at, "
    "created_by, created_at, updated_at) VALUES (:id, :t, :team, 's', 'open', 'normal', :at, :at, 'u', :at, :at)"
)


def test_each_team_with_work_gets_every_version_and_no_type_is_left_without_a_team(database_url: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, BEFORE)
    t, at = new_id("ten"), now_iso()
    seed_type = f"write_approval_{t[-6:]}"
    own_type = f"risk_only_{t[-6:]}"
    asyncio.run(
        _sql(
            database_url,
            (CASE, {"id": new_id("case"), "t": t, "team": "team_ops", "at": at}),
            (CASE, {"id": new_id("case"), "t": t, "team": "team_risk", "at": at}),
            (HEAD, {"t": t, "id": seed_type, "team": None, "origin": "seed", "at": at}),
            (VERSION, {"t": t, "id": seed_type, "v": 1, "r": '{"name": "v1"}', "at": at}),
            (VERSION, {"t": t, "id": seed_type, "v": 2, "r": '{"name": "v2"}', "at": at}),
            (HEAD, {"t": t, "id": own_type, "team": "team_risk", "origin": "team", "at": at}),
            (VERSION, {"t": t, "id": own_type, "v": 1, "r": '{"name": "mine"}', "at": at}),
        )
    )
    command.upgrade(cfg, "head")
    heads, versions = asyncio.run(
        _sql(
            database_url,
            ("SELECT team_id, id, origin FROM task_types WHERE tenant_id = :t ORDER BY team_id, id", {"t": t}),
            (
                "SELECT team_id, type_id, version FROM task_type_versions WHERE tenant_id = :t "
                "ORDER BY team_id, type_id, version",
                {"t": t},
            ),
        )
    )
    assert [tuple(r) for r in heads] == [
        ("team_ops", seed_type, "seed"),
        ("team_risk", own_type, "team"),
        ("team_risk", seed_type, "seed"),
    ], "a copy in each team with work, the team's own type untouched, none without a team"
    assert [tuple(r) for r in versions] == [
        ("team_ops", seed_type, 1),
        ("team_ops", seed_type, 2),
        ("team_risk", own_type, 1),
        ("team_risk", seed_type, 1),
        ("team_risk", seed_type, 2),
    ], "every version is copied, so a task pinned to v1 still reads it"
    command.downgrade(cfg, BEFORE)
    (back,) = asyncio.run(
        _sql(database_url, ("SELECT team_id, id FROM task_types WHERE tenant_id = :t ORDER BY id", {"t": t}))
    )
    assert [tuple(r) for r in back] == [("team_risk", own_type), ("team_ops", seed_type)]
    command.upgrade(cfg, "head")
    asyncio.run(
        _sql(
            database_url,
            ("DELETE FROM task_type_versions WHERE tenant_id = :t", {"t": t}),
            ("DELETE FROM task_types WHERE tenant_id = :t", {"t": t}),
            ("DELETE FROM cases WHERE tenant_id = :t", {"t": t}),
        )
    )
