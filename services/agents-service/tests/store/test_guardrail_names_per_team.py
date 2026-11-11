"""The guardrail slug key on the database a team runs on, by failure mode: the key still spans every team, so the
second team's guardrail of one name is refused by PostgreSQL; and the key is dropped without a replacement, so one
team can hold two guardrails of one name. The route tests run on SQLite built from the table definitions, which never
meets a migration, so this runs the migrations."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
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
