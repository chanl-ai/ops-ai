"""The skills list in SQL (`store/skill_list.py`) and the pins it counts (`agent_skill_pins`), by failure mode: a save,
a pin removed or an agent deleted leaving the pins table behind the agent's newest version, so `usedBy` counts an
agent that no longer pins the skill; another team's skills on the page, or another team's agents counted in `usedBy`,
when the database lets every team through."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.agent_registry import AgentRegistry, agent_skill_pins
from ops_agents.store.skill_list import skills_page
from ops_agents.store.skills import SkillRegistry
from ops_agents.store.tenancy import tenant_tx
from ops_service_kit.listing import ListParams
from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.team_scope import acting_as
from ops_store.testing import DATABASES, NO_SQL_SERVER, sql_server_schema

ROOT = Path(__file__).resolve().parents[2]
TEAM, OTHER = "team_cards", "team_lending"
BY = "maya@x.example"


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
    e = create_async_engine(url)
    yield e
    await e.dispose()


@pytest.fixture
def tenant() -> str:
    return f"t_{uuid4().hex[:10]}"


def _spec(name: str, *pins: tuple[str, int]) -> dict[str, Any]:
    return {"name": name, "role": "r", "model": "m", "skillPins": [{"skillId": s, "version": v} for s, v in pins]}


async def _pins(e: AsyncEngine, agent_id: str) -> set[tuple[str, int, str]]:
    p = agent_skill_pins.c
    async with tenant_tx(e) as c:
        found = await c.execute(sa.select(p.skill_id, p.version, p.team_id).where(p.agent_id == agent_id))
        return {(str(s), int(v), str(t)) for s, v, t in found}


async def _skill(e: AsyncEngine, name: str, team: str, *kbs: str) -> str:
    slug = name.lower().replace(" ", "-")
    content: dict[str, Any] = {
        "name": name,
        "slug": slug,
        "useWhen": "u",
        "loading": "on_match",
        "tools": [],
        "knowledgeBases": list(kbs),
    }
    return await SkillRegistry(e).create(
        content, owner_team="Retail", team_id=team, origin="blank", by=BY, published=True
    )


async def test_the_pins_table_follows_a_save_a_removed_pin_and_a_delete(engine: AsyncEngine, tenant: str) -> None:
    reg = AgentRegistry(engine)
    with isolation.scope(tenant, TEAM):
        agent = await reg.create(_spec("Card desk", ("sk_a", 1), ("sk_b", 2), ("sk_a", 3)), by=BY, team_id=TEAM)
        created = await _pins(engine, agent)
        await reg.save(agent, _spec("Card desk", ("sk_b", 3)), by=BY)
        removed = await _pins(engine, agent)
        await reg.save(agent, _spec("Card desk"), by=BY)
        emptied = await _pins(engine, agent)
        await reg.save(agent, _spec("Card desk", ("sk_c", 1)), by=BY)
        await reg.delete(agent)
        deleted = await _pins(engine, agent)
    assert (created, removed, emptied, deleted) == (
        {("sk_a", 1, TEAM), ("sk_b", 2, TEAM)},
        {("sk_b", 3, TEAM)},
        set(),
        set(),
    )


async def test_the_page_and_its_used_by_hold_the_acting_team_when_the_policy_lets_every_team_through(
    engine: AsyncEngine, tenant: str
) -> None:
    reg = AgentRegistry(engine)
    with isolation.scope(tenant, TEAM):
        mine = await _skill(engine, "Card dispute", TEAM, "kb_cards")
        await reg.create(_spec("Card desk", (mine, 1)), by=BY, team_id=TEAM, published=True)
    with isolation.scope(tenant, OTHER):
        theirs = await _skill(engine, "Loan hardship", OTHER, "kb_loans", "kb_cards")
        # Another team's agent pins this team's skill: it is not this team's to count.
        await reg.create(_spec("Loan desk", (mine, 1), (theirs, 1)), by=BY, team_id=OTHER, published=True)
    # Tenant-wide with a team acting, so the database policy lets every team through and the query alone holds them.
    reason = "a test reads the skills list with every team let through"
    with isolation.tenant_wide(reason, tenant_id=tenant), acting_as(TEAM):
        page, counts = await skills_page(engine, ListParams(), view="all")
        bases = [["kb_loans", "kb_cards"], ["kb_loans"]]
        held = [await skills_page(engine, ListParams(filters={"knowledgeBases": b}), view="all") for b in bases]
    seen = [(r["id"], r["used_by"], r["live_agents"]) for r in page["data"]]
    assert (seen, counts["all"], page["facets"]["status"]) == ([(mine, 1, 1)], 1, {"published": 1})
    # The knowledge base filter keeps the team's skill naming any base given, never another team's.
    assert [[r["id"] for r in p["data"]] for p, _ in held] == [[mine], []]
