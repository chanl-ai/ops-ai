"""Every GET route of agents-service in its statement budget (`budgets.toml`, data-access standard DA1 and DA6), by
failure mode: a list whose statements grow with its rows, a route over its row, and a route that opens more
transactions or checks out more connections than its row lists. The app runs on the dev caller's seeded team; the
lists `seed_team` adds rows to are named in its docstring, and a list it does not fill proves nothing about growth."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response

from ops_agents.api.agent_registry import SEED_TEAM
from ops_service_kit.settings import Settings
from ops_service_kit.testing import Seeded, SeedTeam, StatementBudget, budget_check
from ops_store.database import open_database

from ..conftest import SEED, emptied, started
from .test_case_record_route_pins import DISPUTE
from .test_guardrails_route_pins import RULE
from .test_skills_route_pins import SKILL
from .test_widget_registry import LIMIT_CARD

BUDGETS = Path(__file__).parents[2] / "budgets.toml"
BASIC = Path(__file__).parents[1] / "fixtures" / "engine" / "basic.yaml"
# The dev caller acting in the seeded team, as the console sends it: the team lists read that team's rows.
DEV = {"X-Team-Id": SEED_TEAM}
# `{workflow_id}` names a registry workflow and, under `definitions/`, an engine definition: one seeded id each.
REGISTRY_WORKFLOW, DEFINITION = "wire_hold_review", "refund_check"
PATH_IDS = (
    "agent_id",
    "batch_id",
    "case_id",
    "copy",
    "guardrail_id",
    "mailbox_id",
    "name",
    "request_id",
    "resource",
    "review_id",
    "run_id",
    "run_key",
    "skill_id",
    "slug",
    "task_id",
    "thread_id",
    "tool_id",
    "type_id",
    "version",
    "widget_id",
    "workflow_id",
)

statement_budget = pytest.fixture(budget_check)


@pytest.fixture
async def served(graph_models: Any, database_url: str) -> AsyncIterator[tuple[FastAPI, AsyncClient]]:
    """The app on an engine from `open_database`, whose listeners count each request's statements, transactions and
    connection checkouts into its `http.request` line."""
    engine = open_database(database_url)
    await emptied(engine)
    settings = Settings(database_url=database_url, seed_dir=SEED)
    try:
        async with started(engine, settings, graph_models) as made:
            yield made
    finally:
        await engine.dispose()


@pytest.fixture
def app(served: tuple[FastAPI, AsyncClient]) -> FastAPI:
    return served[0]


class Caller:
    """The test's client as the budget calls it: an engine definition's path gets the definition's id, which the
    shared `{workflow_id}` template cannot carry."""

    def __init__(self, client: AsyncClient) -> None:
        self.client = client

    async def get(self, url: str, *, headers: Mapping[str, str]) -> Response:
        if url.startswith(f"/v1/workflows/definitions/{REGISTRY_WORKFLOW}"):
            url = url.replace(REGISTRY_WORKFLOW, DEFINITION, 1)
        return await self.client.get(url, headers=headers)


@pytest.fixture
def client(served: tuple[FastAPI, AsyncClient]) -> Caller:
    return Caller(served[1])


def _id(answer: Any) -> str:
    assert answer.status_code in (200, 201), answer.text
    data = answer.json()["data"]
    return str(data.get("id") or data["widgetId"])


@pytest.fixture
def seed_team(served: tuple[FastAPI, AsyncClient]) -> SeedTeam:
    """`n` more agents, skills, guardrails, widgets and cases on the dev caller's team, beside the seed folder's
    records; the path ids name the first of each, and the seeded fraud agent and its records otherwise."""
    client = served[1]
    ids: dict[str, str] = dict.fromkeys(PATH_IDS, "missing")
    ids.update(
        name="dispute_email",
        workflow_id=REGISTRY_WORKFLOW,
        version="1",
        tool_id="lookup_account",
        type_id="budget_type",
    )

    async def seed(n: int) -> Seeded:
        if n == 5:
            # One of each type under one id, which `{type_id}` names in both type routes.
            _id(await client.post("/v1/case-types", json={"id": "budget_type", "name": "Budget type"}, headers=DEV))
            body: dict[str, Any] = {"id": "budget_type", "copyOf": {"id": "write_approval"}, "name": "Budget type"}
            _id(await client.post("/v1/task-types", json=body, headers=DEV))
            body = {"graph": "complex_workflow", "metadata": {}}
            made = await client.post("/v1/threads", json=body, headers=DEV)
            assert made.status_code in (200, 201), made.text
            ids["thread_id"] = str(made.json()["data"]["threadId"])
            made = await client.post("/v1/workflows/definitions", json={"yaml": BASIC.read_text()}, headers=DEV)
            assert made.status_code == 201, made.text
        for i in range(n):
            tag = f"{n}-{i:02d}"
            agent = _id(await client.post("/v1/agents", json={"name": f"Agent {tag}", "role": "Answers"}, headers=DEV))
            skill = _id(await client.post("/v1/skills", json={**SKILL, "name": f"Skill {tag}"}, headers=DEV))
            rule = _id(await client.post("/v1/guardrails", json={**RULE, "name": f"Rule {tag}"}, headers=DEV))
            widget = _id(await client.post("/v1/widgets", json={**LIMIT_CARD, "name": f"Card {tag}"}, headers=DEV))
            case = _id(await client.post("/v1/cases", json={**DISPUTE, "subject": f"Dispute {tag}"}, headers=DEV))
            if i == 0 and n == 5:
                ids.update(agent_id=agent, skill_id=skill, guardrail_id=rule, widget_id=widget, case_id=case)
        return Seeded(headers=DEV, ids=ids)

    return seed


async def test_every_get_stays_in_its_budget(statement_budget: StatementBudget) -> None:
    problems = await statement_budget(BUDGETS)
    assert problems == [], "\n".join(problems)
