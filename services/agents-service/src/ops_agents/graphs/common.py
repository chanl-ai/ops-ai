"""What every graph node needs, and running a kernel turn inside a node with its events on the run stream."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Protocol

from langgraph.config import get_config, get_stream_writer

from ops_agent_kernel.events import (
    CitationsReady,
    SkillLoaded,
    StatusChanged,
    TextDelta,
    TextReplaced,
    ToolInputAvailable,
    ToolOutput,
    TurnFinished,
)
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts, ToolExecutor, ToolOutcome
from ops_agent_kernel.types import (
    AgentSettings,
    Interrupt,
    PendingCall,
    PromptFragment,
    ToolCallRecord,
    ToolGrant,
    TurnRequest,
    TurnResult,
)
from ops_agents.activities.catalog import AgentDefinition, Catalog
from ops_agents.activities.tool_directory import CatalogTools, ToolDirectory, grants_for
from ops_agents.activities.tools import ReplySender
from ops_metering import Usage

from .metering import Meter, metered
from .models import GraphModels
from .usage import report_usage


@dataclass(frozen=True)
class GraphDeps:
    catalog: Catalog
    ports: KernelPorts
    models: GraphModels
    replies: ReplySender
    model_alias: str
    # Reads an attachment's text by file id when state carries a reference instead of the bytes (E4, E6).
    files: FileReader | None = None
    # Checks each model call against the thread's budget and records its usage (E12); None meters nothing.
    meter: Meter | None = None
    # Starts a published workflow as a child thread when an agent calls it as a tool; None offers no workflow tools.
    workflows: WorkflowRunner | None = None
    # The tools an agent may be granted (tools-service's registry); None reads the fixture catalogue (unit tests).
    tools: ToolDirectory | None = None
    # Runs a specialist agent's turn when the team's default agent calls it as a tool (c-174); None offers none.
    agents: AgentRunner | None = None
    # What the agent remembers about the turn's person (c-124): their profile and search_memory; None remembers nothing.
    memory: MemoryRunner | None = None


async def needs_step_up(deps: GraphDeps, tool: str) -> bool:
    """Whether approving a call to `tool` needs a step-up: its operation asks for one, or two people approve it."""
    ops = await (deps.tools or CatalogTools(deps.catalog)).operations()
    return any(o.name == tool and (o.approvers > 1 or o.step_up) for o in ops)


async def agent_grants(deps: GraphDeps, agent: AgentDefinition) -> list[ToolGrant]:
    """The registry's grants for the tools `agent` holds, with each one's description and input schema."""
    return await grants_for(deps.tools or CatalogTools(deps.catalog), list(agent.tools))


WORKFLOW_TOOL_PREFIX = "workflow__"


class WorkflowRunner(Protocol):
    """The API side of workflows as agent tools (docs/architecture/workflows-as-tools.md), so this layer does not
    import the API."""

    async def offers(self, granted: list[str]) -> list[ToolGrant]:
        """Tool grants for the `workflow:<id>` names an agent holds whose workflow is published."""
        ...

    async def run(
        self,
        *,
        workflow: str,
        arguments: dict[str, Any],
        key: str,
        parent_thread_id: str,
        parent_run_id: str | None,
        graph_input: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> ToolOutcome:
        """Finds or creates the child thread for `key`, runs it, and returns its result or a handle to its review.
        `graph_input` is the child's whole state when it is more than an email; `meta` overrides the thread meta."""
        ...


@dataclass(frozen=True)
class WorkflowTools:
    """The kernel's tool port with workflow tools routed to the runner; every other tool goes to `inner`."""

    inner: ToolExecutor
    runner: WorkflowRunner

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        if not tool.startswith(WORKFLOW_TOOL_PREFIX):
            return await self.inner.execute(tool, arguments, key=key, approval_token=approval_token)
        configurable = get_config().get("configurable") or {}
        return await self.runner.run(
            workflow=tool.removeprefix(WORKFLOW_TOOL_PREFIX),
            arguments=arguments,
            key=key,
            parent_thread_id=str(configurable["thread_id"]),
            parent_run_id=configurable.get("run_id"),
        )


AGENT_TOOL_PREFIX = "agent__"
MEMORY_TOOL = "search_memory"


class MemoryRunner(Protocol):
    """The API side of memory (c-124), so this layer does not import the API."""

    async def profile(self, agent_id: str) -> PromptFragment | None:
        """The turn's person's remembered facts and preferences as one fragment; None when there are none."""
        ...

    async def offers(self, agent_id: str) -> list[ToolGrant]:
        """The `search_memory` grant when the agent remembers and the turn has a person."""
        ...

    async def run(self, arguments: dict[str, Any]) -> ToolOutcome: ...


@dataclass(frozen=True)
class MemoryTools:
    """The kernel's tool port with `search_memory` routed to the memory runner."""

    inner: ToolExecutor
    runner: MemoryRunner

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        if tool != MEMORY_TOOL:
            return await self.inner.execute(tool, arguments, key=key, approval_token=approval_token)
        return await self.runner.run(arguments)


class AgentRunner(Protocol):
    """The API side of specialist agents as tools (c-174), so this layer does not import the API."""

    async def offers(self, agent_id: str) -> list[ToolGrant]:
        """`agent__<id>` grants for the specialists `agent_id` may ask on this turn: none unless it is its team's
        default agent, the turn has a person, and the turn is not itself a specialist's."""
        ...

    async def run(
        self, *, agent: str, arguments: dict[str, Any], key: str, parent_thread_id: str, parent_run_id: str | None
    ) -> ToolOutcome:
        """Runs `agent`'s own turn on the question for the turn's person and returns its reply."""
        ...


@dataclass(frozen=True)
class AgentTools:
    """The kernel's tool port with specialist calls routed to the runner; every other tool goes to `inner`."""

    inner: ToolExecutor
    runner: AgentRunner

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        if not tool.startswith(AGENT_TOOL_PREFIX):
            return await self.inner.execute(tool, arguments, key=key, approval_token=approval_token)
        configurable = get_config().get("configurable") or {}
        return await self.runner.run(
            agent=tool.removeprefix(AGENT_TOOL_PREFIX),
            arguments=arguments,
            key=key,
            parent_thread_id=str(configurable["thread_id"]),
            parent_run_id=configurable.get("run_id"),
        )


async def ports_with_workflows(
    deps: GraphDeps, granted: list[str], *, agent_id: str | None = None
) -> tuple[KernelPorts, list[ToolGrant]]:
    """The ports and extra grants for an agent turn: workflow tools for its granted, published workflows, and for the
    team's default agent the specialists the person may ask."""
    ports, offers = deps.ports, list[ToolGrant]()
    if deps.workflows is not None and (
        found := await deps.workflows.offers([g for g in granted if g.startswith("workflow:")])
    ):
        ports, offers = replace(ports, tools=WorkflowTools(ports.tools, deps.workflows)), found
    if deps.agents is not None and agent_id and (specialists := await deps.agents.offers(agent_id)):
        ports, offers = replace(ports, tools=AgentTools(ports.tools, deps.agents)), [*offers, *specialists]
    if deps.memory is not None and agent_id and (search := await deps.memory.offers(agent_id)):
        ports, offers = replace(ports, tools=MemoryTools(ports.tools, deps.memory)), [*offers, *search]
    return ports, offers


async def with_memory(deps: GraphDeps, settings: AgentSettings, agent_id: str) -> AgentSettings:
    """The turn's settings with the person's remembered profile after the agent's own instructions (c-124)."""
    if deps.memory is None or (fragment := await deps.memory.profile(agent_id)) is None:
        return settings
    return replace(settings, instructions=[*settings.instructions, fragment])


class FileReader(Protocol):
    async def read_file(self, file_id: str) -> str: ...


def reply_call(email: Mapping[str, object], draft: str, review_id: str) -> dict[str, Any]:
    """The send_reply call a review approves. The human node puts it in the interrupt and the send node makes exactly
    this call, so the approval token, bound to its input, matches what runs."""
    return {
        "tool": "send_reply",
        "input": {"to": email["sender"], "subject": f"Re: {email['subject']}", "body": draft},
        "step": f"{review_id}:reply",
    }


def approval_token(decision: dict[str, Any] | None) -> str | None:
    """The review service's token from an approved decision; it rides in the checkpointed decision, so a resume in a
    new process still has it."""
    d = decision or {}
    return d.get("approval_token") if d.get("decision") == "approved" else None


def emit(event: str, node: str, data: Any = None) -> None:
    """Puts one event on the run's stream (LangGraph `custom` mode); a no-op outside a streamed run."""
    try:
        writer = get_stream_writer()
    except RuntimeError:
        return
    writer({"event": event, "node": node, "data": data})


async def kernel_turn(
    node: str, req: TurnRequest, ports: KernelPorts, meter: Meter | None = None, alias: str = "-"
) -> TurnResult:
    """Runs one kernel turn, streaming its text and tool events from this node, metered as one call (E12)."""
    return await metered(meter, alias, "turn", lambda: _kernel_turn(node, req, ports), record=False)


def _call_data(c: ToolCallRecord) -> dict[str, Any]:
    """The whole call as plain data, so a reader of the event log can show it without the kernel's types."""
    return {
        "id": c.tool_call_id,
        "tool": c.tool,
        "server": c.server,
        "access": c.access,
        "input": c.input,
        "output": c.output,
        "status": c.status,
        "durationMs": c.duration_ms,
        "view": c.view,
    }


async def _kernel_turn(node: str, req: TurnRequest, ports: KernelPorts) -> TurnResult:
    result: TurnResult | None = None
    async for ev in run_turn(req, ports):
        match ev:
            case StatusChanged(phase=phase):
                emit("status", node, phase)
            case TextDelta(delta=delta):
                emit("text", node, delta)
            case TextReplaced(text=text):
                emit("text_replaced", node, text)
            case ToolInputAvailable(call=c):
                emit("tool_start", node, _call_data(c))
            case ToolOutput(call=c):
                emit("tool_end", node, _call_data(c))
            case CitationsReady(citations=refs):
                emit(
                    "citation",
                    node,
                    [
                        {
                            "n": r.n,
                            "documentId": r.passage.document_id,
                            "title": r.passage.title,
                            "section": r.passage.section,
                            "version": r.passage.version,
                            **({"page": r.passage.page} if r.passage.page else {}),
                            "snippet": r.passage.text[:280],
                        }
                        for r in refs
                    ],
                )
            case SkillLoaded(skill_id=sid, version=v, name=name, matched=matched):
                # The run journal's record of each load (spec 11 5.3.7).
                emit("skill_loaded", node, {"skillId": sid, "version": v, "name": name, "matched": matched})
            case TurnFinished(result=r):
                result = r
                # The audit record of what a guardrail kept from the person (withheld, never shown) or took back
                # after it streamed (retracted, what they saw before the replacement); the conversation shows neither.
                for kind, text in (("withheld", r.withheld), ("retracted", r.retracted)):
                    if text:
                        emit(
                            f"guardrail_{kind}",
                            node,
                            {"guardrail": r.guardrail, "stopReason": r.stop_reason, "text": text},
                        )
                emit(
                    "turn",
                    node,
                    {
                        "model": r.model_name,
                        "status": r.status,
                        "noAnswer": r.no_answer,
                        "error": r.error,
                        "errorCode": r.error_code,
                        # Which guardrails this turn checked and which the builder switched off.
                        "guardrails": {"checked": r.guardrails_checked, "off": r.guardrails_off},
                        # The streamed text is replaced by the checked one when a guardrail rewrote the answer.
                        **({"guardrail": r.guardrail, "text": r.text} if r.guardrail else {}),
                    },
                )
            case _:
                pass
    assert result is not None, "run_turn always ends with TurnFinished"
    u = result.usage
    report_usage(Usage(u.input_tokens, u.output_tokens, max(u.requests, 1)))
    return result


def interrupt_to_state(i: Interrupt) -> dict[str, Any]:
    """An Interrupt as plain data the checkpointer can store; the library history travels base64-encoded."""
    p = i.pending_call
    return {
        "interrupt_id": i.interrupt_id,
        "needed": i.needed,
        "tool_call_id": p.tool_call_id,
        "key": p.key,
        "action_id": p.action_id,
        "tool": p.tool,
        "server": p.server,
        "access": p.access,
        "input": p.input,
        "input_hash": p.input_hash,
        "history": base64.b64encode(i.history).decode(),
        "loaded_skills": i.loaded_skills,
    }


def interrupt_from_state(d: dict[str, Any]) -> Interrupt:
    call = PendingCall(
        tool_call_id=d["tool_call_id"],
        key=d["key"],
        action_id=d["action_id"],
        tool=d["tool"],
        server=d["server"],
        access=d["access"],
        input=d["input"],
        input_hash=d["input_hash"],
    )
    return Interrupt(
        d["interrupt_id"],
        "approval",
        d["needed"],
        call,
        base64.b64decode(d["history"]),
        list(d.get("loaded_skills") or []),
    )
