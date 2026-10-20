"""Task assist (c-302) on PostgreSQL with the real worker and the review view, by failure mode: assist runs with the
setting off; a model call is made per read instead of once per task; a suggestion names an action the type does not
have; a failing model call holds or fails the task; the call reads run data the task does not show."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api import engine_reviews
from ops_agents.api.engine_agents import StepRules
from ops_agents.api.engine_host import RunReviews, assisted_reviews
from ops_agents.api.task_assist import PENDING_LIMIT, TaskAssist, kernel_assist
from ops_agents.api.task_type_seeds import StoredTaskTypes
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.task_assists import TaskAssistStore, task_assists
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.ports import AgentResult, PromptRequest
from ops_engine.store import DefinitionStore, RunStore
from ops_service_kit.ids import new_id
from tests.conftest import structured
from tests.engine.test_worker import CountingTools, drain, worker
from tests.unit.test_agent_step_port import _prompt_port, _streamed  # pyright: ignore[reportPrivateUsage]

FLOW = parse(
    {
        "schemaVersion": 2,
        "id": "assisted",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            {
                "id": "review",
                "type": "ops.flow.humanReview",
                "typeVersion": 1,
                "parameters": {
                    "title": "Decide",
                    "taskType": {"id": "generic_decision"},
                    "params": {"title": "Open the case for {$.input.name}?", "facts": "$.input.facts"},
                },
            },
            {"id": "ok", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "approved"}},
            {"id": "no", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "rejected"}},
        ],
        "connections": [
            {"from": {"node": "start", "port": "payload"}, "to": {"node": "review", "port": "in"}},
            {"from": {"node": "review", "port": "approve"}, "to": {"node": "ok", "port": "in"}},
            {"from": {"node": "review", "port": "reject"}, "to": {"node": "no", "port": "in"}},
        ],
    }
)
HELP = {
    "question": "Should a levy case open for Marcus Bell?",
    "summary": "A 3,250.00 levy from Nova Scotia Supreme Court.",
    "doubtful": ["amount"],
    "suggestion": {"action": "approve", "reason": "The notice names the debtor and an amount."},
}


class Prompts:
    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.requests: list[PromptRequest] = []

    async def prompt(self, request: PromptRequest) -> AgentResult:
        self.requests.append(request)
        if isinstance(self.answer, Exception):
            raise self.answer
        return AgentResult(True, self.answer)


# The RunReviews each _paused call built, so a test can wait for its assist after reading the task first.
rt_reviews: list[RunReviews] = []


class Slow(Prompts):
    """Answers only once released: a model call that takes as long as the test says."""

    def __init__(self, answer: Any) -> None:
        super().__init__(answer)
        self.release = asyncio.Event()

    async def prompt(self, request: PromptRequest) -> AgentResult:
        await self.release.wait()
        return await super().prompt(request)


class DenyAll:
    async def rules(self, run_id: str | None) -> StepRules:
        return StepRules(False, True)


class Policies:
    def __init__(self, on: bool) -> None:
        self.on = on

    async def value(self, key: str) -> Any:
        return {"team_a": True} if self.on else {}


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def _paused(
    engine: AsyncEngine, prompts: Prompts, *, on: bool, settle: bool = True, reviews: RunReviews | None = None
) -> tuple[str, str, Any]:
    tenant = f"t-{uuid4().hex[:8]}"
    tx = EngineTransactions(engine)
    with tenant_scope(tenant):
        version, _ = await DefinitionStore(tx).publish(
            FLOW.id, name="Assisted", definition=FLOW.wire(), digest=FLOW.digest(), now="n", by="a@x", stage="live"
        )
        run_id = new_id("wfrun")
        facts = [{"label": "Amount", "value": "3,250.00"}]
        run = {"id": run_id, "team_id": "team_a", "workflow_id": FLOW.id, "version": version, "digest": FLOW.digest()}
        # `secret` is in the run's input but on no region: the assist must never read it.
        given = {"name": "Marcus Bell", "facts": facts, "secret": "SIN 123-456-789"}
        await RunStore(tx).create(run | {"run_key": run_id, "mode": "live", "input": given, "created_by": "a@x"})
    w = worker(engine, CountingTools(), InMemorySaver())
    w.host.ports.task_types = StoredTaskTypes(engine)
    reviews = reviews or RunReviews(TaskAssist(engine, prompts, Policies(on)), tx)
    w.host.ports.reviews = reviews
    await drain(w)
    if settle:
        await reviews.settled()
    rt_reviews.append(reviews)
    rt: Any = SimpleNamespace(db=engine, settings=SimpleNamespace(lease_ttl_seconds=6.0, review_sla_hours=24.0))
    return tenant, run_id, rt


async def _regions(rt: Any, tenant: str, run_id: str) -> dict[str, Any]:
    with tenant_scope(tenant):
        return {r["region"]: r["data"] for r in (await engine_reviews.get(rt, run_id))["task"]["regions"]}


async def test_with_assist_on_one_call_writes_help_every_read_shows(engine: AsyncEngine) -> None:
    prompts = Prompts(HELP)
    tenant, run_id, rt = await _paused(engine, prompts, on=True)
    first, second = await _regions(rt, tenant, run_id), await _regions(rt, tenant, run_id)
    assert first["assist"] == {**HELP, "ai": True} and second["assist"] == first["assist"]
    assert len(prompts.requests) == 1, "one call per task, not per read"
    # The call reads what the task shows, never the rest of the run.
    assert "Marcus Bell" in prompts.requests[0].message and "SIN" not in prompts.requests[0].message


async def test_with_assist_off_no_call_is_made_and_no_help_shows(engine: AsyncEngine) -> None:
    prompts = Prompts(HELP)
    tenant, run_id, rt = await _paused(engine, prompts, on=False)
    assert "assist" not in await _regions(rt, tenant, run_id) and prompts.requests == []


async def test_a_suggestion_of_an_action_the_type_lacks_is_dropped(engine: AsyncEngine) -> None:
    tenant, run_id, rt = await _paused(
        engine, Prompts({**HELP, "suggestion": {"action": "escalate", "reason": "x"}}), on=True
    )
    assist = (await _regions(rt, tenant, run_id))["assist"]
    assert assist["suggestion"] is None and assist["question"] == HELP["question"]


async def test_a_failing_model_leaves_the_task_open_without_help(engine: AsyncEngine) -> None:
    tenant, run_id, rt = await _paused(engine, Prompts(RuntimeError("models-service is down")), on=True)
    regions = await _regions(rt, tenant, run_id)
    assert "assist" not in regions and regions["header"] == {"title": "Open the case for Marcus Bell?"}


async def test_a_slow_assist_does_not_hold_the_task_back(engine: AsyncEngine) -> None:
    """tick 30: the pause waited up to 20 s on the assist's model call before the task could be shown; and a task read
    before the assist is written must say it is coming, or the page never shows it (uc-234)."""
    prompts = Slow(HELP)
    tenant, run_id, rt = await _paused(engine, prompts, on=True, settle=False)
    first = await _regions(rt, tenant, run_id)
    # Shown at once, saying the assist is on its way, so the page knows to read the task again.
    assert first["assist"] == {"pending": True, "ai": True} and "header" in first, first
    prompts.release.set()
    await rt_reviews[-1].settled()
    assert (await _regions(rt, tenant, run_id))["assist"] == {**HELP, "ai": True}


async def test_the_workers_assist_runs_whatever_the_ai_step_rules_say(engine: AsyncEngine) -> None:
    """tick 31: the worker's assist borrowed the AI step port, whose rules refuse a call that names no run, so every
    assist failed as ai_steps_off. Built as the worker builds it, under AI step rules that refuse everything."""

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return structured(info, HELP)

    agents = _prompt_port(_streamed(answer))
    agents.rules = DenyAll()
    assist = kernel_assist(engine, agents, Policies(True))
    step = f"wfrun_{uuid4().hex[:8]}:review:1"
    payload: dict[str, Any] = {"taskType": {"id": "generic_decision"}, "step_id": step, "params": {"title": "Open it?"}}
    with tenant_scope(f"t-{uuid4().hex[:8]}"):
        await assist.write("team_a", payload)
        assert await TaskAssistStore(engine).get(step) == HELP


async def test_a_stopping_worker_waits_for_the_assist_it_is_writing(engine: AsyncEngine) -> None:
    """tick 31: the assist ran in an untracked task, so a worker stopping mid-call lost it and the task stayed pending.
    Built as the worker builds it; the model answers only after the stop has begun."""

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return structured(info, HELP)

    async def slow(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str]:
        await asyncio.sleep(0.3)
        yield json.dumps(HELP)

    agents = _prompt_port(FunctionModel(answer, stream_function=slow))
    async with AsyncExitStack() as stack:
        reviews = assisted_reviews(stack, engine, agents, Policies(True))
        tenant, run_id, rt = await _paused(engine, Prompts(HELP), on=True, settle=False, reviews=reviews)
    assert (await _regions(rt, tenant, run_id))["assist"] == {**HELP, "ai": True}


async def test_an_assist_still_pending_past_its_limit_reads_as_failed(engine: AsyncEngine) -> None:
    """tick 32: a worker killed mid-call leaves the assist pending for ever, and the console polls it for ever."""
    prompts = Slow(HELP)
    tenant, run_id, rt = await _paused(engine, prompts, on=True, settle=False)
    assert (await _regions(rt, tenant, run_id))["assist"] == {"pending": True, "ai": True}
    long_ago = (datetime.now(UTC) - PENDING_LIMIT - timedelta(seconds=1)).isoformat()
    with tenant_scope(tenant):
        async with engine.begin() as c:
            await c.execute(task_assists.update().where(task_assists.c.tenant_id == tenant).values(created_at=long_ago))
        assert "assist" not in await _regions(rt, tenant, run_id)
    prompts.release.set()
    await rt_reviews[-1].settled()
