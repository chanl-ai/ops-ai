"""A budget held at the model gateway, by failure mode: a call past the cap still reached the provider; and a retry of
the same step, once the cap is raised, was answered with the refusal instead of making the refused call."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from pydantic_ai import Agent
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agent_kernel.models import ModelsServiceModels
from ops_agent_kernel.ports import BudgetReachedError
from ops_agents.api.budgets import BudgetedModel, gateway_budgets, spending_from, step_budget
from ops_agents.graphs.metering import step_calls
from ops_agents.store.tenancy import tenant_scope
from ops_metering import Budget
from ops_service_kit.settings import Settings
from tests.conftest import SEED
from tests.model_gateway import ALIAS, Models, models_gateway


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
    model = BudgetedModel(
        ModelsServiceModels("http://models", m.secret, http_client=m.completions).model_for(ALIAS), budgets, ALIAS
    )
    run = f"wfrun_{uuid4().hex[:10]}"
    budget_id = step_budget(run, "ai")

    async def step() -> list[str]:
        said: list[str] = []
        with step_calls(f"{run}:ai:0"), spending_from(budget_id):
            for i in range(4):
                said.append((await Agent(model, output_type=str).run(f"Question {i}?")).output)
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
