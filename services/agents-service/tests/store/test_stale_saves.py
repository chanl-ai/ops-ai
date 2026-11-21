"""Saves that name the copy they read, made at the same moment, by failure mode: the store comparing the base before
it holds the row, so several saves made from one copy all pass and each writes over the one before it. A workflow's
working copy is one field (the whole canvas), so it is held to this even when one person saves from several tabs."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.agent_registry import AgentRegistry, digest_of
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.skills import SkillRegistry
from ops_engine.store import DefinitionStore
from ops_service_kit.errors import Conflict
from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.testing import DATABASES, NO_SQL_SERVER, sql_server_schema

ROOT = Path(__file__).resolve().parents[2]
TEAM = "team_cards"
SAVERS = 6


@pytest.fixture(scope="module", params=DATABASES)
def url(request: pytest.FixtureRequest) -> Iterator[str]:
    if request.param == "postgresql":
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        yield Settings().database_url
        return
    with sql_server_schema("agents", os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")) as u:
        if u is None:
            pytest.skip(NO_SQL_SERVER)
        yield u


@pytest.fixture
async def engine(url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(url, pool_size=SAVERS)
    yield e
    await e.dispose()


async def _outcomes(saves: list[Any]) -> tuple[int, list[str]]:
    """How many of the saves were written, and the code each refused one was refused with."""
    done = await asyncio.gather(*saves, return_exceptions=True)
    refused = [r.code for r in done if isinstance(r, Conflict)]
    assert all(isinstance(r, (int, Conflict)) for r in done), done
    return len(done) - len(refused), refused


async def test_six_saves_made_from_one_copy_at_once_write_one_and_refuse_five(engine: AsyncEngine) -> None:
    agents, skills = AgentRegistry(engine), SkillRegistry(engine)
    name = f"Card dispute {uuid4().hex[:8]}"
    content: dict[str, Any] = {
        "name": name,
        "slug": name.lower().replace(" ", "-"),
        "useWhen": "u",
        "loading": "on_match",
    }
    spec: dict[str, Any] = {"name": "Card desk", "role": "r", "model": "m"}
    with isolation.scope(f"t_{uuid4().hex[:10]}", TEAM):
        agent = await agents.create(spec, by="maya@x.example", team_id=TEAM)
        skill = await skills.create(content, owner_team="Retail", team_id=TEAM, origin="blank", by="maya@x.example")
        # Every saver read the same copy: version 1 with the digest of what was created.
        on_agent = await _outcomes(
            [
                agents.save(agent, {**spec, "role": f"r{i}"}, by=f"p{i}@x.example", base=(1, digest_of(spec)))
                for i in range(SAVERS)
            ]
        )
        on_skill = await _outcomes(
            [
                skills.save_draft(
                    skill, {**content, "useWhen": f"u{i}"}, by=f"p{i}@x.example", note="", base=(1, digest_of(content))
                )
                for i in range(SAVERS)
            ]
        )
    assert (on_agent, on_skill) == ((1, ["stale_base"] * 5), (1, ["stale_base"] * 5))


async def test_six_tabs_saving_one_workflow_copy_at_once_write_one(engine: AsyncEngine) -> None:
    store = DefinitionStore(EngineTransactions(engine))
    wid = f"card_disputes_{uuid4().hex[:8]}"
    first: dict[str, Any] = {"schemaVersion": 2, "id": wid, "name": "Card disputes", "nodes": [], "connections": {}}
    with isolation.scope(f"t_{uuid4().hex[:10]}", TEAM):
        await store.publish(wid, name="Card disputes", definition=first, digest=digest_of(first), now="n", by="maya")

        def save(name: str, base: tuple[int, str]) -> Any:
            d = first | {"name": name}
            return store.put_working_copy(
                wid, definition=d, digest=digest_of(d), checks=[], base=base, now="n", by="maya@x.example"
            )

        opened = await save("Opened", (1, digest_of(first)))
        # One person in six tabs, each saving its own canvas on the copy every tab opened on.
        tabs = [save(f"Tab {i}", (1, opened.digest)) for i in range(SAVERS)]
        done = await asyncio.gather(*tabs, return_exceptions=True)
    assert sorted(type(r).__name__ for r in done) == ["StaleWorkingCopy"] * (SAVERS - 1) + ["WorkingCopy"], done


async def test_an_autosave_locks_only_the_newest_version_row(engine: AsyncEngine) -> None:
    """Every autosave runs this lock, so locking every version with its whole definition costs more the longer a
    workflow lives and holds rows a publish of any version waits on."""
    store = DefinitionStore(EngineTransactions(engine))
    wid = f"loan_intake_{uuid4().hex[:8]}"
    with isolation.scope(f"t_{uuid4().hex[:10]}", TEAM):
        for i in range(4):
            d: dict[str, Any] = {"schemaVersion": 2, "id": wid, "name": f"Loan intake {i}", "nodes": []}
            await store.publish(wid, name=d["name"], definition=d, digest=digest_of(d), now="n", by="maya")
        newest = await store.row(wid)
        assert newest is not None and newest.version == 4
        seen: list[str] = []

        def record(_c: Any, _cur: Any, statement: str, *_: Any) -> None:
            if "FROM engine_definitions" in statement and ("FOR UPDATE" in statement or "UPDLOCK" in statement):
                seen.append(statement)

        event.listen(engine.sync_engine, "before_cursor_execute", record)
        try:
            d = {"schemaVersion": 2, "id": wid, "name": "Edited", "nodes": []}
            await store.put_working_copy(
                wid, definition=d, digest=digest_of(d), checks=[], base=(4, newest.digest), now="n", by="maya"
            )
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", record)
    assert len(seen) == 1, seen
    assert "engine_definitions.definition" not in seen[0], seen[0]
    assert "LIMIT" in seen[0] or "TOP" in seen[0], seen[0]
