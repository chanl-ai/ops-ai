"""The Evals lists in SQL (`store/assurance_list.py`) and the workflow test run counts they read (agents 0117), by
failure mode: two suites of one name repeating or vanishing between pages, a page past the end answering nothing, a
facet or the total disagreeing with the rows; another team's suites, runs or figures listed when the database lets every
team through; a test run stored before 0117 left without the counts the lists filter on, or the down path leaving a
database 0116 cannot run on."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.agent_registry import AgentRegistry
from ops_agents.store.assurance_list import Checks, runs_page, stats, suites_page
from ops_agents.store.evals import EvalStore
from ops_agents.store.tenancy import tenant_tx
from ops_service_kit.http import Json
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.listing import ListParams
from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.team_scope import acting_as
from ops_store.testing import DATABASES, NO_SQL_SERVER, sql_server_schema

from .test_drop_publish_policies import _sql  # pyright: ignore[reportPrivateUsage]

ROOT = Path(__file__).resolve().parents[2]
TEAM, OTHER = "team_cards", "team_lending"
BY = "maya@x.example"
TIER = "medium"
CASE: dict[str, Any] = {"name": "greets", "input": "Hello", "checks": []}


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


async def _agent(e: AsyncEngine, agent_id: str, name: str, team: str, *, passed: int | None) -> None:
    """An agent with one saved case and, unless `passed` is None, one run of it."""
    spec: Json = {"name": name, "role": "r", "model": "m"}
    await AgentRegistry(e).create(spec, by=BY, team_id=team, agent_id=agent_id)
    store = EvalStore(e)
    await store.replace_cases("agent", agent_id, team, [CASE], by=BY)
    if passed is not None:
        row: dict[str, Any] = {
            "id": new_id("evr"),
            "team_id": team,
            "kind": "agent",
            "asset_id": agent_id,
            "version": 1,
            "trigger": "manual",
            "passed": passed,
            "total": 1,
            "regressions": 0,
            "duration_ms": 5,
            "results": [],
            "started_by": BY,
            "ran_at": now_iso(),
        }
        await store.add_run(row)


async def test_equal_names_hold_one_order_a_page_past_the_end_answers_the_last_and_facets_match(
    engine: AsyncEngine, tenant: str
) -> None:
    suffix = uuid4().hex[:6]
    ids = [f"ag_{n}{suffix}" for n in ("c", "a", "b")]
    with isolation.scope(tenant, TEAM):
        for agent_id, passed in zip(ids, (1, 0, None), strict=True):
            await _agent(engine, agent_id, "Payee Checker", TEAM, passed=passed)
        async with tenant_tx(engine) as c:
            pages = [await suites_page(c, ListParams(page=n, page_size=1), tier=TIER) for n in (1, 2, 3, 9)]
            failing = await suites_page(c, ListParams(filters={"result": ["failing"]}), tier=TIER)
    assert [p["data"][0]["asset_id"] for p in pages] == [*sorted(ids), sorted(ids)[-1]]
    assert (pages[3]["pagination"]["page"], pages[0]["pagination"]["total"]) == (3, 3)
    assert [r["asset_id"] for r in failing["data"]] == [ids[1]]
    assert failing["facets"]["result"] == {"failing": 1, "passing": 1, "not_run": 1}
    assert failing["pagination"]["total"] == 1


async def test_lists_and_figures_hold_the_acting_team_when_the_policy_lets_every_team_through(
    engine: AsyncEngine, tenant: str
) -> None:
    mine, theirs = f"ag_m{uuid4().hex[:6]}", f"ag_t{uuid4().hex[:6]}"
    with isolation.scope(tenant, TEAM):
        await _agent(engine, mine, "Card desk", TEAM, passed=1)
    with isolation.scope(tenant, OTHER):
        await _agent(engine, theirs, "Loan desk", OTHER, passed=0)
    # Tenant-wide with a team acting, so the database policy lets every team through and the query alone holds them.
    reason = "a test reads the evals lists with every team let through"
    with isolation.tenant_wide(reason, tenant_id=tenant), acting_as(TEAM):
        async with tenant_tx(engine) as c:
            suites, listed = await suites_page(c, ListParams(), tier=TIER), await runs_page(c, ListParams())
            figures = await stats(c, checks=Checks(tier=TIER, blocking=frozenset({"pass_rate"}), min_pass_rate=0.8))
    assert [r["asset_id"] for r in suites["data"]] == [mine]
    assert [r["asset_id"] for r in listed["data"]] == [mine]
    assert (figures.suites, figures.runs, figures.failing_suites) == (1, 1, 0)


def test_runs_stored_before_gain_their_counts_and_the_down_path_runs(emptied_database: str) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    before = "0116_tool_catalog_copies"
    command.downgrade(cfg, before)
    tenant, other, at = new_id("ten"), new_id("ten"), now_iso()
    insert = (
        "INSERT INTO registry_validations (tenant_id, id, workflow_id, ran_at, target, results, summary) "
        "SELECT CASE WHEN n % 2 = 0 THEN :t ELSE :o END, 'val_' || n, 'wf_x', :at, 'draft', CAST('[]' AS json), "
        "CAST(:s AS json) FROM generate_series(1, 1001) n"
    )
    summary = json.dumps({"passed": 2, "total": 3, "regressions": 1, "checksFailing": 4})
    asyncio.run(
        _sql(
            emptied_database,
            # One more than a batch (BATCH in 0117), half in another tenant, and one summary with no counts.
            (insert, {"t": tenant, "o": other, "at": at, "s": summary}),
            (
                "INSERT INTO registry_validations (tenant_id, id, workflow_id, ran_at, target, results, summary) "
                "VALUES (:t, 'val_bare', 'wf_x', :at, 'draft', CAST('[]' AS json), CAST('{}' AS json))",
                {"t": tenant, "at": at},
            ),
        )
    )
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")
    (found,) = asyncio.run(
        _sql(
            emptied_database,
            (
                "SELECT passed, total, regressions, checks_failing, COUNT(*) FROM registry_validations "
                "GROUP BY passed, total, regressions, checks_failing ORDER BY passed",
                {},
            ),
        )
    )
    assert found == [(0, 0, 0, 0, 1), (2, 3, 1, 4, 1001)]
    command.downgrade(cfg, before)
    command.upgrade(cfg, "head")
    asyncio.run(_sql(emptied_database, ("DELETE FROM registry_validations WHERE workflow_id = 'wf_x'", {})))
