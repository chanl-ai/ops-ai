"""A workflow AI step's model call through the model gateway, its runs on PostgreSQL and SQL Server, by failure mode: a
step re-run after a crash called the model again; a changed request was answered from an old record; a record did not
survive a restart; and a step whose record was written but whose done mark was not paid twice on resume."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agent_kernel.models import ModelsServiceModels
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.testing import Answer, Structured, last_user_text
from ops_agents.api.budgets import BudgetedModel
from ops_agents.api.engine_agents import KernelPrompts
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine import default_registry
from ops_engine.compiler import channel, compile_definition
from ops_engine.definition import parse
from ops_engine.journal import MemoryJournal, StepRow
from ops_engine.ports import AgentResult, EnginePorts, PromptRequest
from ops_engine.store import SqlJournal
from ops_service_kit.http import Json
from ops_store.testing import DATABASES, NO_SQL_SERVER, sql_server_schema
from tests.model_gateway import ALIAS, Models, models_gateway


class Killed(BaseException):
    """Stands in for SIGKILL: not an Exception, so nothing in the engine catches it."""


@pytest.fixture(scope="module", params=DATABASES)
def url(request: pytest.FixtureRequest) -> Iterator[str]:
    if request.param == "postgresql":
        yield request.getfixturevalue("database_url")
        return
    with sql_server_schema("agents", os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")) as ms:
        if ms is None:
            pytest.skip(NO_SQL_SERVER)
        yield ms


@pytest.fixture
async def engine(url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(url)
    yield e
    await e.dispose()


class Model:
    """The scripted provider behind the gateway: a summary of what it was asked, and a count of the calls it was paid
    for. A call the gateway answers from its record never reaches it."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, messages: list[Json], tools: list[Json]) -> Answer:
        self.calls += 1
        return Structured({"summary": f"call {self.calls}: {last_user_text(messages)[-40:]}"})


@pytest.fixture
async def gateway(database_url: str) -> AsyncIterator[tuple[Models, Model]]:
    """models-service on the PostgreSQL test database, whichever database the runs use."""
    model, e = Model(), create_async_engine(database_url)
    try:
        async with models_gateway(e, model) as m:
            yield m, model
    finally:
        await e.dispose()


class NoTools:
    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        raise AssertionError("no tool runs")


class NoKnowledge:
    async def search(self, query: str, kb_ids: list[str]) -> list[Any]:
        return []


class CrashOnce:
    """The step's prompt port: the real one, and the first time a crash right after the model answered."""

    def __init__(self, inner: KernelPrompts, *, crash: bool) -> None:
        self.inner, self.crash = inner, crash

    async def prompt(self, request: PromptRequest) -> AgentResult:
        result = await self.inner.prompt(request)
        if self.crash:
            self.crash = False
            raise Killed
        return result


class DoneMarkLost(SqlJournal):
    """The journal whose first done mark of a finished step never commits: the process died writing it."""

    lost = False

    async def finish(self, row: StepRow, **kw: Any) -> None:
        if not self.lost and row.node_id == "ai" and kw.get("status") == "ok":
            DoneMarkLost.lost = True
            raise Killed
        await super().finish(row, **kw)


SUMMARISE = parse(
    {
        "schemaVersion": 2,
        "id": "replay",
        "nodes": [
            {"id": "in", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            {"id": "ai", "type": "ops.ai.summarise", "typeVersion": 1, "parameters": {"text": "$.input.body"}},
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "ok"}},
            {"id": "bad", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "error"}},
        ],
        "connections": [
            {"from": {"node": "in", "port": "payload"}, "to": {"node": "ai", "port": "in"}},
            {"from": {"node": "ai", "port": "ok"}, "to": {"node": "done", "port": "in"}},
            {"from": {"node": "ai", "port": "error"}, "to": {"node": "bad", "port": "in"}},
        ],
    }
)


def graph(db: AsyncEngine, m: Models, saver: InMemorySaver, *, crash: bool = False, journal: Any = None) -> Any:
    """The step as the worker compiles it, with a fresh model and prompt port each time: a process (re)started."""
    through = ModelsServiceModels("http://models", m.secret, http_client=m.completions)
    kernel = KernelPorts(BudgetedModel(through.model_for(ALIAS), None, ALIAS), NoTools(), NoKnowledge())  # type: ignore[arg-type]
    prompts = CrashOnce(KernelPrompts(kernel, ALIAS), crash=crash)
    ports = EnginePorts(tools=NoTools(), reviews=None, prompts=prompts)  # type: ignore[arg-type]
    return compile_definition(
        SUMMARISE,
        default_registry(),
        ports=ports,
        journal=journal or SqlJournal(EngineTransactions(db)),
        checkpointer=saver,
    )


def config(run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": run_id, "run_id": run_id}}


async def summary(g: Any, run_id: str) -> str:
    step = (await g.aget_state(config(run_id))).values[channel("ai")]
    assert step["port"] == "ok", step
    return str(step["out"]["summary"])


async def test_a_step_re_run_after_a_crash_is_answered_from_its_record(
    engine: AsyncEngine, gateway: tuple[Models, Model]
) -> None:
    (m, model), tenant, run_id = gateway, f"t-{uuid4().hex[:8]}", f"wfrun_{uuid4().hex[:10]}"
    with tenant_scope(tenant):
        with pytest.raises(Killed):
            await graph(engine, m, InMemorySaver(), crash=True).ainvoke(
                {"input": {"body": "Card lost"}}, config(run_id), durability="sync"
            )
        paid = model.calls  # the turn's calls (its answer, then the kernel's check of it)
        # The crash also lost the checkpoint written before the step: the run starts again from its trigger, whose
        # journal answers for it, so the step runs under a new LangGraph task.
        again = graph(engine, m, InMemorySaver())
        await again.ainvoke({"input": {"body": "Card lost"}}, config(run_id), durability="sync")
        assert model.calls == paid, "the re-run paid for the model calls again"
        assert (await summary(again, run_id)).startswith("call 1")


async def test_a_changed_request_is_never_answered_from_an_old_record(
    engine: AsyncEngine, gateway: tuple[Models, Model]
) -> None:
    (m, model), tenant = gateway, f"t-{uuid4().hex[:8]}"
    run_id = f"wfrun_{uuid4().hex[:10]}"
    with tenant_scope(tenant):
        with pytest.raises(Killed):
            await graph(engine, m, InMemorySaver(), crash=True, journal=MemoryJournal()).ainvoke(
                {"input": {"body": "Card lost"}}, config(run_id), durability="sync"
            )
        paid = model.calls
        # The same run and step asked about something else (its run started over with a new input): its own call,
        # never the record of the first request.
        g = graph(engine, m, InMemorySaver(), journal=MemoryJournal())
        await g.ainvoke({"input": {"body": "Card stolen abroad"}}, config(run_id), durability="sync")
        assert model.calls == 2 * paid and "stolen" in await summary(g, run_id), await summary(g, run_id)


async def test_a_record_survives_a_restart(url: str, gateway: tuple[Models, Model]) -> None:
    (m, model), saver = gateway, InMemorySaver()
    tenant, run_id = f"t-{uuid4().hex[:8]}", f"wfrun_{uuid4().hex[:10]}"
    before = create_async_engine(url)
    with tenant_scope(tenant):
        with pytest.raises(Killed):
            await graph(before, m, saver, crash=True).ainvoke(
                {"input": {"body": "Card lost"}}, config(run_id), durability="sync"
            )
        paid = model.calls
        await before.dispose()
        after = create_async_engine(url)  # the worker restarted: a new process, new connections
        try:
            await graph(after, m, saver).ainvoke(None, config(run_id), durability="sync")
        finally:
            await after.dispose()
    assert model.calls == paid, "the record was not there after the restart"


async def test_a_step_whose_done_mark_was_lost_does_not_pay_twice(
    engine: AsyncEngine, gateway: tuple[Models, Model]
) -> None:
    (m, model), saver = gateway, InMemorySaver()
    tenant, run_id = f"t-{uuid4().hex[:8]}", f"wfrun_{uuid4().hex[:10]}"
    DoneMarkLost.lost = False
    with tenant_scope(tenant):
        journal = DoneMarkLost(EngineTransactions(engine))
        with pytest.raises(Killed):
            await graph(engine, m, saver, journal=journal).ainvoke(
                {"input": {"body": "Card lost"}}, config(run_id), durability="sync"
            )
        paid = model.calls
        await graph(engine, m, saver, journal=journal).ainvoke(None, config(run_id), durability="sync")
    assert model.calls == paid, "the step paid for its model calls again on resume"
