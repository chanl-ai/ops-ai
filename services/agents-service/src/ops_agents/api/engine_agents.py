"""The workflow runner's AgentPort in agents-service: an agent step runs one kernel turn of the agent's published
version, on the same kernel ports a chat turn uses (its model through models-service when configured, its granted
tools through the tool gateway, its knowledge bases through kb-service).

The turn's id is the step's (run:node:iteration), so its tool keys repeat on a re-run and the gateway answers a write
once; inside the worker the LangGraph config names the run as the thread, so the model-call ledger replays a
recorded response on a re-run instead of calling the model again.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol

from ops_agent_kernel.events import TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.models import ModelsServiceModels, NoModelKeyError, build_model
from ops_agent_kernel.ports import KernelPorts
from ops_agent_kernel.types import AgentSettings, PromptFragment, TurnRequest, TurnResult
from ops_agents.activities.catalog import AgentDefinition, Catalog, load_catalog
from ops_agents.activities.gateway import GatewayClient, GatewayToolExecutor
from ops_agents.activities.knowledge import KbService, Knowledge, NoKnowledgeService
from ops_agents.activities.overrides import Overrides, limits_for
from ops_agents.activities.overrides import resolve as resolve_settings
from ops_agents.activities.tool_directory import CatalogTools, ToolDirectory, ToolsOperations, grants_for
from ops_agents.activities.tools import LocalToolExecutor
from ops_engine.ports import AgentRequest, AgentResult, PromptRequest
from ops_identity import ServiceClient
from ops_metering import PriceTable
from ops_service_kit.errors import NotFound, Unprocessable
from ops_service_kit.settings import Settings

from ..store.agent_registry import AgentRegistry
from ..store.engine import AsyncEngine
from ..store.usage import UsageLedger
from .agent_registry import definition_of
from .model_ledger import LedgerModel, LedgerSource


class AgentUnavailableError(RuntimeError):
    """The step's agent is unknown, unpublished or paused, or the turn could not reach a model."""


AI_STEPS_OFF = (
    "AI steps are off for this team. Someone who may manage workflow settings turns on AI steps in workflows."
)


@dataclass(frozen=True)
class StepRules:
    """What a team's settings say about its AI steps, read live: whether they may run (aiSteps, c-298) and whether
    people reading its runs see personal data masked (aiStepsMaskPersonalData, c-321)."""

    allowed: bool
    masks: bool


class RunRules(Protocol):
    async def rules(self, run_id: str | None) -> StepRules:
        """The rules for the team the run is in."""
        ...


@dataclass
class KernelPrompts:
    """The engine's PromptPort and the AI step route's (c-298): one kernel call per step under its team's rules. A team
    with AI steps off is refused here at run, not only when a workflow is saved, so turning the setting off stops
    the steps already saved."""

    ports: KernelPorts
    model_alias: str
    rules: RunRules | None = None

    async def prompt(self, request: PromptRequest) -> AgentResult:
        """No saved agent, so no tools, no knowledge and no agent limits; the step's model alias, else the workspace's.
        Without a rules source every step runs, masked."""
        rules = await self.rules.rules(request.run_id) if self.rules is not None else StepRules(True, True)
        if not rules.allowed:
            return AgentResult(False, error=AI_STEPS_OFF, code="ai_steps_off")
        result = await kernel_call(
            self.ports,
            key=request.turn_id,
            instructions=request.instructions,
            message=request.message,
            schema=request.output_schema,
            model_alias=request.model_alias or self.model_alias,
            agent_id="workflow_step",
            # Real in the step's output, for the steps after it; masked where people read the run (c-321).
            redact_pii=False,
        )
        if result.status == "completed":
            return AgentResult(True, result.output, result.text)
        if result.stop_reason in ("schema_error", "no_output"):
            # As an agent step's: a retry repeats the same call and its spend, so the error port takes it at once.
            return AgentResult(False, text=result.text, error=result.error, code=result.stop_reason)
        raise AgentUnavailableError(result.error or f"the model call stopped: {result.stop_reason}")


async def kernel_call(
    ports: KernelPorts,
    *,
    key: str,
    instructions: str,
    message: str,
    schema: dict[str, Any],
    model_alias: str,
    agent_id: str,
    redact_pii: bool = False,
) -> TurnResult:
    """One kernel turn with no tools and no knowledge whose answer must match `schema`, on `model_alias`: memory
    extraction's call and every AI step's (c-298). The ledger records it under `key`; each caller reads the result its
    own way."""
    req = TurnRequest(
        turn_id=key,
        run_id=key,
        settings=AgentSettings(
            agent_id=agent_id,
            version=1,
            instructions=[PromptFragment(instructions, True)],
            model_alias=model_alias,
            max_tool_calls=0,
            max_steps=2,
            redact_pii=redact_pii,
        ),
        tools=[],
        transcript=[],
        user_turn=message,
        kb_ids=[],
        output_schema=schema,
    )
    result: TurnResult | None = None
    async for event in run_turn(req, ports):
        if isinstance(event, TurnFinished):
            result = event.result
    assert result is not None, "run_turn always ends with TurnFinished"
    return result


@dataclass
class KernelAgents:
    db: AsyncEngine
    catalog: Catalog
    ports: KernelPorts
    directory: ToolDirectory
    model_alias: str
    # The rules each AI step's run follows (aiSteps, aiStepsMaskPersonalData); without them every step runs, masked.
    rules: RunRules | None = None

    async def turn(self, request: AgentRequest) -> AgentResult:
        reg = AgentRegistry(self.db)
        try:
            row = await reg.row(request.agent_id)
        except NotFound as e:
            raise AgentUnavailableError(f"agent {request.agent_id} does not exist") from e
        if row["published_version"] is None or row["paused"]:
            raise AgentUnavailableError(f"agent {request.agent_id} is not published and live")
        version = int(row["published_version"])
        agent = definition_of(request.agent_id, version, (await reg.version(request.agent_id, version))["spec"])
        try:
            settings = self._step_settings(agent, request)
        except Unprocessable as e:
            # A model the agent does not allow is the step's setting, not a passing fault: the error port, no retry.
            return AgentResult(False, error=str(e), code="step_setting")
        req = TurnRequest(
            turn_id=request.turn_id,
            run_id=request.turn_id,
            settings=settings,
            tools=await grants_for(self.directory, list(agent.tools)),
            transcript=[],
            user_turn=request.message,
            kb_ids=agent.default_kb_ids,
            output_schema=request.output_schema,
        )
        result: TurnResult | None = None
        async for event in run_turn(req, self.ports):
            if isinstance(event, TurnFinished):
                result = event.result
        assert result is not None, "run_turn always ends with TurnFinished"
        if result.status == "completed":
            return AgentResult(True, result.output, result.text)
        if result.stop_reason in ("schema_error", "no_output"):
            # The answer is wrong, or the turn ended without one (a tool limit, a refusal, no knowledge): a retry
            # repeats the same turn and its spend, so the step's error port takes it at once, with the reason.
            return AgentResult(False, text=result.text, error=result.error, code=result.stop_reason)
        # Anything else (no model, a refused call, a paused write) is a failed attempt: the wrapper retries it, then
        # takes the error port.
        raise AgentUnavailableError(result.error or f"the turn stopped: {result.stop_reason}")

    async def prompt(self, request: PromptRequest) -> AgentResult:
        """An AI step's call (c-298), through the one prompt port the AI step route also uses."""
        return await KernelPrompts(self.ports, self.model_alias, self.rules).prompt(request)

    def _step_settings(self, agent: AgentDefinition, request: AgentRequest) -> AgentSettings:
        """The agent's settings with the step's own: its model through the override resolver, so the agent's limits
        still decide which models are allowed, and its tool-call cap, which can only lower the agent's."""
        effective = None
        if request.model_alias:
            limits = limits_for(agent, self.model_alias)
            effective = resolve_settings(limits, agent.default_kb_ids, turn=Overrides(model=request.model_alias))
        settings = self.catalog.settings_for(agent, self.model_alias, effective)
        if request.max_tool_calls is not None:
            caps = [c for c in (settings.max_tool_calls, request.max_tool_calls) if c is not None]
            settings = replace(settings, max_tool_calls=min(caps))
        # Workflow data stays real so a later step (a Send) gets the real address; people's reads of the run mask it
        # (c-321, tick 31). The agent's redactPii still masks its chats.
        return replace(settings, redact_pii=False)


@dataclass
class KernelModels:
    """One structured model call (memory extraction, c-206): one kernel turn with no tools and no knowledge, on the
    deployment's alias, whose answer must match the JSON Schema. The kernel's ledger records the call under `key`."""

    ports: KernelPorts
    model_alias: str

    async def structured(self, system: str, user: str, schema: dict[str, Any], *, key: str) -> Any:
        result = await kernel_call(
            self.ports,
            key=key,
            instructions=system,
            message=user,
            schema=schema,
            model_alias=self.model_alias,
            agent_id="extract",
        )
        if result.status == "completed":
            return result.output
        if result.stop_reason == "schema_error":
            # The step checks the answer itself and asks again once; an answer it cannot read counts as empty.
            return result.output if result.output is not None else {}
        raise AgentUnavailableError(result.error or f"the model call stopped: {result.stop_reason}")


def kernel_agents(
    settings: Settings,
    db: AsyncEngine,
    *,
    gateway: GatewayClient | None,
    tools: ServiceClient | None,
    kb: ServiceClient | None,
) -> KernelAgents | None:
    """The agent port the worker hands the engine, built as create_app builds a chat turn's ports; None when no model
    is configured (an agent step then fails with that reason)."""
    catalog = load_catalog(settings.seed_dir, settings.agents_seed_file)
    through: ModelsServiceModels | None = None
    if settings.models_url and settings.models_key is not None:
        through = ModelsServiceModels(settings.models_url, settings.models_key.get_secret_value())
        model = through.model_for(settings.model_alias)
    else:
        try:
            model = build_model(settings)
        except NoModelKeyError:
            return None
    usage = UsageLedger(db, PriceTable.parse(settings.prices))
    directory: ToolDirectory = ToolsOperations(tools) if tools is not None else CatalogTools(catalog)
    executor = GatewayToolExecutor(gateway, directory) if gateway is not None else LocalToolExecutor(catalog)
    knowledge: Knowledge = KbService(kb) if kb is not None else NoKnowledgeService()
    ports = KernelPorts(
        model=LedgerModel(model, usage, settings.model_alias),
        tools=executor,
        knowledge=knowledge,
        models=LedgerSource(through, usage) if through is not None else None,
    )
    return KernelAgents(db, catalog, ports, directory, settings.model_alias)
