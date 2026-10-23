"""Migration 0075 (c-507) gives every workflow definition a team but the background processes, by failure mode: a
definition one team ran is left readable by every team; a background process loses its account-level handler; an
unused no-team definition survives; a definition two teams ran is given to one of them and the other's runs are left
pointing at a definition it cannot read."""

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
BEFORE = "0074_types_per_team"

DEFINITION = (
    "INSERT INTO engine_definitions (tenant_id, workflow_id, version, digest, name, definition, created_at, "
    "created_by, team_id, stage) VALUES (:t, :w, 1, :w, :w, CAST('{}' AS json), :at, 'a@x', NULL, 'live')"
)
RUN = (
    "INSERT INTO engine_runs (id, tenant_id, team_id, workflow_id, version, digest, run_key, mode, status, created_by, "
    "created_at, updated_at) VALUES (:id, :t, :team, :w, 1, :w, :id, 'live', 'succeeded', 'a@x', :at, :at)"
)


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


def _seed(url: str, t: str, at: str, *rows: tuple[str, list[str]]) -> None:
    statements: list[tuple[str, dict[str, Any]]] = []
    for workflow, teams in rows:
        statements.append((DEFINITION, {"t": t, "w": workflow, "at": at}))
        statements += [(RUN, {"id": new_id("wfrun"), "t": t, "team": team, "w": workflow, "at": at}) for team in teams]
    asyncio.run(_sql(url, *statements))


def _clean(url: str, t: str) -> None:
    asyncio.run(
        _sql(
            url,
            ("DELETE FROM engine_runs WHERE tenant_id = :t", {"t": t}),
            ("DELETE FROM engine_definitions WHERE tenant_id = :t", {"t": t}),
        )
    )


def test_one_teams_definition_is_placed_the_unused_one_goes_and_the_handler_stays(database_url: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, BEFORE)
    t, at = new_id("ten"), now_iso()
    _seed(database_url, t, at, ("api_task", ["team_ops", "team_risk"]), ("ran_once", ["team_ops"]), ("unused", []))
    try:
        command.upgrade(cfg, "head")
        (rows,) = asyncio.run(
            _sql(
                database_url,
                ("SELECT workflow_id, team_id FROM engine_definitions WHERE tenant_id = :t ORDER BY 1", {"t": t}),
            )
        )
        assert [tuple(r) for r in rows] == [("api_task", None), ("ran_once", "team_ops")]
    finally:
        _clean(database_url, t)


def test_a_definition_two_teams_ran_is_copied_and_the_second_teams_runs_move_to_the_copy(database_url: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    command.downgrade(cfg, BEFORE)
    t, at = new_id("ten"), now_iso()
    _seed(database_url, t, at, ("shared_flow", ["team_ops", "team_risk"]))
    try:
        command.upgrade(cfg, "head")
        definitions, runs = asyncio.run(
            _sql(
                database_url,
                ("SELECT workflow_id, team_id FROM engine_definitions WHERE tenant_id = :t ORDER BY 1", {"t": t}),
                ("SELECT workflow_id, team_id FROM engine_runs WHERE tenant_id = :t ORDER BY 1", {"t": t}),
            )
        )
        assert [tuple(r) for r in definitions] == [("shared_flow", "team_ops"), ("shared_flow_team_risk", "team_risk")]
        assert [tuple(r) for r in runs] == [("shared_flow", "team_ops"), ("shared_flow_team_risk", "team_risk")]
    finally:
        _clean(database_url, t)
