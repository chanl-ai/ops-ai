"""A budget held at the model gateway, by failure mode: a call past the cap still reached the provider; and a retry of
the same step, once the cap is raised, was answered with the refusal instead of making the refused call."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agent_kernel import structured
from ops_agent_kernel.events import TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.models import ModelsServiceModels
from ops_agent_kernel.ports import BudgetReachedError, KernelPorts, ToolOutcome
from ops_agent_kernel.testing import Answer, Reply, ToolCall, tool_names, trailing_tool_results
from ops_agent_kernel.types import AgentSettings, Passage, PromptFragment, ToolGrant, TurnRequest
from ops_agents.api.budgets import budgeted, gateway_budgets, spending_from, step_budget
from ops_agents.graphs.metering import step_calls
from ops_agents.store.tenancy import tenant_scope
from ops_metering import Budget
from ops_service_kit.http import Json
from ops_service_kit.settings import Settings
from tests.conftest import SEED
from tests.model_gateway import ALIAS, Models, models_gateway

CASES = ToolGrant(
    "find_cases", "ops", "Find cases", "read", {"type": "object", "properties": {"search": {"type": "string"}}}
)
SETTINGS = AgentSettings("ag_ops", 1, [PromptFragment("You are Ops Assistant.")], ALIAS)


class Cases:
    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        return ToolOutcome(True, {"cards": [], "summary": "2 cases"})


class NoKnowledge:
    async def search(self, query: str, kb_ids: list[str]) -> list[Passage]:
        return []


@pytest.fixture
async def gateway(database_url: str) -> AsyncIterator[tuple[Models, AsyncEngine]]:
    engine = create_async_engine(database_url)
    try:
        async with models_gateway(engine, lambda messages, tools: "Noted.") as m:
            yield m, engine
    finally:
        await engine.dispose()


async def test_the_fourth_call_on_a_three_call_budget_is_refused_and_a_retry_makes_it(
    gateway: tuple[Models, AsyncEngine],
) -> None:
    m, engine = gateway
    budgets = gateway_budgets(Settings(database_url=str(engine.url), seed_dir=SEED), m.client, engine)
    assert budgets is not None
    model = budgeted(
        ModelsServiceModels("http://models", m.secret, http_client=m.completions).model_for(ALIAS), budgets, ALIAS
    )
    run = f"wfrun_{uuid4().hex[:10]}"
    budget_id = step_budget(run, "ai")

    async def step() -> list[str]:
        said: list[str] = []
        with step_calls(f"{run}:ai:0"), spending_from(budget_id):
            for i in range(4):
                said.append((await structured.ask(model, system="", prompt=f"Question {i}?", purpose="turn")).text)
        return said

    with tenant_scope("local"):
        await budgets.put(budget_id, "step", "team_ops", Budget(max_calls=3))
        with pytest.raises(BudgetReachedError):
            await step()
        assert len(m.provider.requests) == 3, "a call past the cap reached the provider"
        await budgets.put(budget_id, "step", "team_ops", Budget(max_calls=4))
        # The same step again under its replay key: the three answered calls come from the record, the refused one
        # is made now.
        assert await step() == ["Noted."] * 4
    assert len(m.provider.requests) == 4, "the retry did not make the refused call, or paid again for the others"


async def test_a_turn_past_its_budget_stops_calling_the_provider(
    database_url: str,
) -> None:
    def script(messages: list[Json], tools: list[Json]) -> Answer:
        if trailing_tool_results(messages) or not tool_names(tools):
            return "Noted."
        return Reply(tool_calls=[ToolCall("find_cases", {"search": "open"})])

    engine = create_async_engine(database_url)
    try:
        async with models_gateway(engine, script) as m:
            budgets = gateway_budgets(Settings(database_url=str(engine.url), seed_dir=SEED), m.client, engine)
            assert budgets is not None
            model = budgeted(
                ModelsServiceModels("http://models", m.secret, http_client=m.completions).model_for(ALIAS),
                budgets,
                ALIAS,
            )
            run = f"wfrun_{uuid4().hex[:10]}"
            budget_id = step_budget(run, "ai")
            ports = KernelPorts(model=model, tools=Cases(), knowledge=NoKnowledge())
            req = TurnRequest("t1", "th1", SETTINGS, [CASES], user_turn="Which cases are open?")
            with tenant_scope("local"), step_calls(f"{run}:ai:0"), spending_from(budget_id):
                await budgets.put(budget_id, "step", "team_ops", Budget(max_calls=1))
                events = [e async for e in run_turn(req, ports)]
    finally:
        await engine.dispose()
    last = events[-1]
    assert isinstance(last, TurnFinished)
    assert last.result.stop_reason == "budget_reached", last.result
    # After the one call the budget allows, only the tool-less closing answer the gateway lets through at a budget.
    offered = [bool(r.get("tools")) for r in m.provider.requests]
    assert offered == [True, False], f"a call past the budget reached the provider: {offered}"
