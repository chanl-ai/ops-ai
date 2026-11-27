"""The workflow worker's agent port (api/engine_agents.py), by failure mode: a turn that ends without its structured
answer (knowledge out of reach, a refusal, a tool limit) raised as unavailable, so the step retried the same turn and
paid for it again before failing (customer_summary on shared, 2026-10-18: two attempts, 16 model calls); a step's
tool-call cap that does not bound a model that keeps calling tools; a step's model the agent does not allow used
anyway."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agent_kernel.contract import ModelEndpoint
from ops_agent_kernel.ports import KernelPorts, KnowledgeUnavailableError, ToolOutcome
from ops_agent_kernel.testing import Answer, Reply, Script, Structured, ToolCall, tool_names
from ops_agents.activities.catalog import load_catalog
from ops_agents.activities.tool_directory import OperationRef
from ops_agents.api.engine_agents import KernelAgents, StepRules
from ops_agents.store.agent_registry import AgentRegistry
from ops_agents.store.base import metadata
from ops_engine.ports import AgentRequest, PromptRequest
from ops_service_kit.http import Json
from tests.conftest import SEED, calls_in, model_on

SCHEMA: dict[str, Any] = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]}


class NoTools:
    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        raise AssertionError("no tool runs")


class KnowledgeDown:
    async def search(self, query: str, kb_ids: list[str]) -> list[Any]:
        raise KnowledgeUnavailableError("kb-service is down")


class NoDirectory:
    async def operations(self) -> list[Any]:
        return []


def answers(messages: list[Json], tools: list[Json]) -> Answer:
    return Reply(tool_calls=[ToolCall("final_result", {"summary": "never asked"})])


async def test_a_turn_without_its_answer_takes_the_error_port_without_a_retry(local_tenant: None) -> None:
    db = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with db.begin() as c:
        await c.run_sync(metadata.create_all)
    spec: Json = {"name": "Advisor", "role": "Summarises customers", "instructions": "", "collections": ["kb_people"]}
    aid = await AgentRegistry(db).create(spec, by="seed", team_id="team_ops", agent_id="ag_x", published=True)
    port = KernelAgents(
        db,
        load_catalog(SEED),
        KernelPorts(model_on(answers), NoTools(), KnowledgeDown()),
        NoDirectory(),
        "default",  # type: ignore[arg-type]
    )
    result = await port.turn(
        AgentRequest(agent_id=aid, message="Summarise Priya", turn_id="r:summarise:1", output_schema=SCHEMA)
    )
    assert (result.ok, result.code, result.output) == (False, "no_output", None), result
    assert result.error and "knowledge" in result.error.lower()


class Reads:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        self.calls += 1
        return ToolOutcome(True, {"id": "CUS-1002", "name": "Priya Natarajan"})


class OneTool:
    async def operations(self) -> list[OperationRef]:
        return [
            OperationRef(
                "get_customer", "One customer", "read", {"type": "object", "properties": {}}, False, None, "Bank"
            )
        ]


def keeps_reading(messages: list[Json], tools: list[Json]) -> Answer:
    # A new customer each time: the kernel answers a repeated identical call from its first result instead.
    return Reply(tool_calls=[ToolCall("get_customer", {"customerId": f"C-{len(messages)}"})])


async def port_on(model: Any, tools: Any, *, spec: dict[str, Any] | None = None) -> tuple[KernelAgents, str]:
    db = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with db.begin() as c:
        await c.run_sync(metadata.create_all)
    spec = spec or {"name": "Advisor", "role": "Summarises customers", "instructions": "", "toolIds": ["get_customer"]}
    aid = await AgentRegistry(db).create(spec, by="seed", team_id="team_ops", agent_id="ag_y", published=True)
    ports = KernelPorts(model, tools, KnowledgeDown())
    return KernelAgents(db, load_catalog(SEED), ports, OneTool(), "default"), aid  # type: ignore[arg-type]


async def test_the_steps_tool_cap_bounds_a_model_that_keeps_calling_tools(local_tenant: None) -> None:
    reads = Reads()
    port, aid = await port_on(model_on(keeps_reading), reads)
    req = AgentRequest(agent_id=aid, message="Summarise", turn_id="r:s:1", output_schema=SCHEMA, max_tool_calls=2)
    result = await port.turn(req)
    assert (result.ok, result.code, reads.calls) == (False, "no_output", 2), (result, reads.calls)


async def test_a_step_model_the_agent_does_not_allow_takes_the_error_port(local_tenant: None) -> None:
    port, aid = await port_on(model_on(answers), Reads())
    req = AgentRequest(
        agent_id=aid, message="Summarise", turn_id="r:s:1", output_schema=SCHEMA, model_alias="not-allowed"
    )
    result = await port.turn(req)
    assert (result.ok, result.code) == (False, "step_setting"), result
    assert result.error and "not-allowed" in result.error


def _streamed(reply: Script) -> ModelEndpoint:
    """`reply` as the kernel's model, answering at the HTTP edge."""
    return model_on(reply)


def _prompt_port(model: ModelEndpoint) -> KernelAgents:
    db = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    return KernelAgents(
        db, load_catalog(SEED), KernelPorts(model, NoTools(), KnowledgeDown()), NoDirectory(), "default"
    )  # type: ignore[arg-type]


async def test_an_ai_step_call_offers_the_model_no_tools_and_returns_its_answer() -> None:
    """An AI step has no saved agent, so the model must be offered nothing to call and no knowledge."""
    offered: list[list[str]] = []

    def answer(messages: list[Json], tools: list[Json]) -> Answer:
        offered.append(sorted(tool_names(tools)))
        return Structured({"summary": "Priya holds two accounts."})

    port = _prompt_port(_streamed(answer))
    result = await port.prompt(
        PromptRequest(
            instructions="Summarise the record.", message="Priya ...", turn_id="r:sum:1", output_schema=SCHEMA
        )
    )
    assert (result.ok, result.output) == (True, {"summary": "Priya holds two accounts."}), result
    assert offered == [[]], offered


async def test_an_ai_step_answer_outside_its_schema_is_an_error_not_a_retry() -> None:
    calls = 0

    def answer(messages: list[Json], tools: list[Json]) -> Answer:
        nonlocal calls
        calls += 1
        return Structured({"wrong": True})

    result = await _prompt_port(_streamed(answer)).prompt(
        PromptRequest(instructions="Summarise.", message="x", turn_id="r:sum:2", output_schema=SCHEMA)
    )
    assert (result.ok, result.code) == (False, "schema_error"), result
    assert calls <= 2, calls


class Rules:
    def __init__(self, *, allowed: bool = True, masks: bool = True) -> None:
        self.value = StepRules(allowed, masks)

    async def rules(self, run_id: str | None) -> StepRules:
        return self.value


async def test_an_ai_steps_output_stays_real_for_the_steps_after_it() -> None:
    """A masked output gave a later Send step "[email]" to send to. Masking is where people read."""
    said: Json = {"summary": "Ann Lee, SSN 123-45-6789, ann.lee@example.com."}

    def answer(messages: list[Json], tools: list[Json]) -> Answer:
        return Structured(said)

    request = PromptRequest(
        instructions="Summarise.", message="x", turn_id="r:sum:3", output_schema=SCHEMA, run_id="wfrun_x"
    )
    port = _prompt_port(_streamed(answer))
    port.rules = Rules(masks=True)
    assert (await port.prompt(request)).output == said


async def test_an_ai_step_whose_team_turned_ai_steps_off_is_refused_at_run() -> None:
    """AiSteps was read only when a workflow was saved, so a team that turned it off still ran its saved
    steps; the prompt port now refuses them without a model call."""
    calls = 0

    def answer(messages: list[Json], tools: list[Json]) -> Answer:
        nonlocal calls
        calls += 1
        return Structured({"summary": "x"})

    port = _prompt_port(_streamed(answer))
    port.rules = Rules(allowed=False)
    request = PromptRequest(instructions="Summarise.", message="x", turn_id="r:s:1", output_schema=SCHEMA, run_id="r")
    result = await port.prompt(request)
    assert (result.ok, result.code, calls) == (False, "ai_steps_off", 0), result


class Searches:
    def __init__(self) -> None:
        self.asked: list[dict[str, Any]] = []

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        self.asked.append(dict(arguments))
        return ToolOutcome(True, {"passages": []})


class SearchTool:
    async def operations(self) -> list[OperationRef]:
        schema = {"type": "object", "properties": {"query": {"type": "string"}, "collections": {"type": "array"}}}
        return [OperationRef("search_knowledge", "Search knowledge", "read", schema, False, None, "Knowledge bases")]


async def test_a_workflow_agent_step_searches_only_its_agents_bases_whatever_the_model_asks(local_tenant: None) -> None:
    """A workflow's agent step ran search_knowledge as the model asked: naming another base, or asking for the whole
    team's, read knowledge the agent was never given."""
    asks = {"query": "salary bands", "collections": ["kb_hr_private"], "allTeamKnowledgeBases": True}

    def reply(messages: list[Json], tools: list[Json]) -> Answer:
        if not calls_in(messages):
            return Reply(tool_calls=[ToolCall("search_knowledge", asks)])
        return Structured({"summary": "Nothing found."})

    searches = Searches()
    db = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with db.begin() as c:
        await c.run_sync(metadata.create_all)
    spec: Json = {"name": "Advisor", "role": "Answers", "instructions": "", "toolIds": ["search_knowledge"],
            "collections": ["kb_people"]}  # fmt: skip
    aid = await AgentRegistry(db).create(spec, by="seed", team_id="team_ops", agent_id="ag_w", published=True)
    ports = KernelPorts(_streamed(reply), searches, NoKnowledge())
    port = KernelAgents(db, load_catalog(SEED), ports, SearchTool(), "default")  # type: ignore[arg-type]
    result = await port.turn(AgentRequest(agent_id=aid, message="Salary bands?", turn_id="r:w:1", output_schema=SCHEMA))
    assert result.ok, result
    assert searches.asked == [{"query": "salary bands", "collections": ["kb_people"]}], searches.asked


class NoKnowledge:
    async def search(self, query: str, kb_ids: list[str]) -> list[Any]:
        return []
