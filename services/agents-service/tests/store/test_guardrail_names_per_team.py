"""The guardrail slug key on the database a team runs on, by failure mode: the key still spans every team, so the
second team's guardrail of one name is refused by PostgreSQL; and the key is dropped without a replacement, so one
team can hold two guardrails of one name. The route tests run on SQLite built from the table definitions, which never
meets a migration, so this runs the migrations."""

from __future__ import annotations

import asyncio
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.ids import new_id, now_iso

ROOT = Path(__file__).resolve().parents[2]

INSERT = (
    "INSERT INTO registry_guardrails (id, slug, name, kind, team_id, owner, version, status, created_at, updated_at) "
    "VALUES (:id, :slug, 'Same rule', 'blocked_topics', :team, 'Ops', 1, 'live', :at, :at)"
)


async def _insert(url: str, slug: str, team: str) -> None:
    engine = create_async_engine(url)
    params: dict[str, Any] = {"id": new_id("grd"), "slug": slug, "team": team, "at": now_iso()}
    try:
        async with engine.begin() as c:
            await c.execute(sa.text("SET LOCAL row_security = off"))
            await c.execute(sa.text(INSERT), params)
    finally:
        await engine.dispose()


def test_the_slug_key_is_per_team_on_the_migrated_database(database_url: str) -> None:
    slug = f"same-rule-{new_id('s')[-8:]}"
    asyncio.run(_insert(database_url, slug, "team_ops"))
    asyncio.run(_insert(database_url, slug, "team_lending"))  # another team: allowed
    with pytest.raises(IntegrityError):
        asyncio.run(_insert(database_url, slug, "team_ops"))  # the same team: refused


SKILL = (
    "INSERT INTO registry_skills (id, slug, owner_team, team_id, origin, version, created_at, updated_at, updated_by) "
    "VALUES (:id, :slug, 'Ops', :team, 'team', 1, :at, :at, 'lee@harborpine.example')"
)


async def _downgrade_refusal(url: str, revision: str, insert: str, slug: str) -> str:
    """The migration's downgrade, run while two teams hold one slug; it must refuse before any DDL."""
    engine = create_async_engine(url)
    module = import_module(f"migrations.versions.{revision}")
    try:
        async with engine.begin() as c:
            await c.execute(sa.text("SET LOCAL row_security = off"))
            for team in ("team_ops", "team_lending"):
                await c.execute(sa.text(insert), {"id": new_id("x"), "slug": slug, "team": team, "at": now_iso()})

            def run(sync_conn: sa.Connection) -> None:
                with Operations.context(MigrationContext.configure(sync_conn)):
                    module.downgrade()

            try:
                await c.run_sync(run)
            except RuntimeError as e:
                return str(e)
            finally:
                await c.rollback()
        return ""
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    ("revision", "insert"),
    [("0101_skill_names_per_team", SKILL), ("0102_guardrail_names_per_team", INSERT)],
)
def test_downgrade_refuses_while_two_teams_hold_one_slug(database_url: str, revision: str, insert: str) -> None:
    message = asyncio.run(_downgrade_refusal(database_url, revision, insert, f"same-{new_id('s')[-8:]}"))
    assert "used by more than one team" in message, message
