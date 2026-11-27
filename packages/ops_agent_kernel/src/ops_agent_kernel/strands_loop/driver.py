"""One turn's model and tool loop on Strands Agents, in the kernel's contract types (contract.py).

The kernel's rules (caps, gates, the step limit) live in the tool bodies and seams it passes in. Strands turns an
exception in a tool body into an error result the model reads, so a body's exception is held here and raised before
the next model request instead: the turn ends the way the kernel decided, and no request is spent after it.
"""

from __future__ import annotations

import copy
import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, cast

import openai
from strands import Agent
from strands.agent.conversation_manager import NullConversationManager
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
from strands.models.openai import OpenAIModel
from strands.tools.executors import SequentialToolExecutor
from strands.types._events import ToolResultEvent, ToolStreamEvent
from strands.types._snapshot import Snapshot
from strands.types.exceptions import EventLoopException, ModelThrottledException
from strands.types.tools import AgentTool, ToolContext, ToolGenerator, ToolSpec, ToolUse

from ops_service_kit.http import Json

from ..contract import (
    CallContext,
    LoopDone,
    LoopEvent,
    LoopPause,
    LoopPaused,
    LoopRefused,
    LoopTool,
    ModelEndpoint,
    SchemaMismatch,
    StepLimitReached,
    StepStarted,
    TextChunk,
    ToolEnded,
    ToolStarted,
    UnofferedTool,
)
from .state import PausedRun, decode, encode

PURPOSE_HEADER = "X-Call-Purpose"
APPROVAL = "approval"
REVIEW = "review"


class _Run:
    """What one run shares between its model, its tools and its hook."""

    def __init__(self, tools: list[LoopTool], step_limit: Callable[[], int | None]) -> None:
        self.tools = {t.name: t for t in tools}
        self.step_limit = step_limit
        self.step = 0
        self.requests = 0
        self.held: BaseException | None = None
        self.events: list[LoopEvent] = []
        self.approved: set[str] = set()
        self.rejected: dict[str, str] = {}
        self.paused: tuple[str, str, Json, str | None] | None = None
        self.purpose = "turn"

    def raise_held(self) -> None:
        if self.held is not None:
            held, self.held = self.held, None
            raise held


class _GatewayModel(OpenAIModel):
    """Strands' OpenAI model with the kernel's step limit, per-step tool offer and system prompt, and each call's
    headers. A refusal comes back as LoopRefused with its status and body, never retried."""

    def __init__(
        self,
        endpoint: ModelEndpoint,
        run: _Run,
        instructions: Callable[[], str],
        params: Json,
        response_format: Json | None,
    ) -> None:
        super().__init__(client=endpoint.client, model_id=endpoint.model_id, params=dict(params))
        self.endpoint = endpoint
        self.run = run
        self.instructions = instructions
        self.response_format = response_format
        self.call_headers: dict[str, str] = {}

    def format_request(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        request = super().format_request(*args, **kwargs)
        request["extra_headers"] = {**self.call_headers}
        if self.response_format is not None:
            request["response_format"] = self.response_format
        return request

    async def stream(  # type: ignore[override]
        self, messages: Any, tool_specs: Any = None, system_prompt: Any = None, **kwargs: Any
    ) -> AsyncIterator[Any]:
        run = self.run
        run.raise_held()
        limit = run.step_limit()
        if limit is not None and run.requests >= limit:
            raise StepLimitReached(f"The run may make {limit} model requests.")
        run.requests += 1
        run.step += 1
        run.events.append(StepStarted(run.step))
        at = CallContext("", run.step)
        specs = cast(list[ToolSpec], tool_specs or [])
        offered = [s for s in specs if (t := run.tools.get(s["name"])) is not None and await t.offered(at)]
        headers = await self.endpoint.headers(run.purpose) if self.endpoint.headers is not None else {}
        self.call_headers = {PURPOSE_HEADER: run.purpose, **headers}
        started = time.perf_counter()
        usage: dict[str, int] = {}
        read = False
        while True:
            try:
                async for event in super().stream(messages, offered or None, self.instructions(), **kwargs):
                    read = True
                    if "metadata" in event:
                        usage = cast(dict[str, int], cast(Json, event["metadata"]).get("usage") or {})
                    yield event
                break
            except (ModelThrottledException, openai.APIStatusError) as e:
                refused = e.__cause__ if isinstance(e, ModelThrottledException) else e
                if not isinstance(refused, openai.APIStatusError):
                    raise
                if not read and self._fall_back(refused.status_code, refused.body):
                    continue
                raise LoopRefused(refused.status_code, refused.body) from refused
        if self.endpoint.answered is not None:
            took = time.perf_counter() - started
            self.endpoint.answered(int(usage.get("inputTokens") or 0), int(usage.get("outputTokens") or 0), took)

    def _fall_back(self, status: int, body: object) -> bool:
        """Moves this run's calls to the endpoint's fallback when it says this refusal falls back."""
        spare, decide = self.endpoint.fallback, self.endpoint.falls_back
        if spare is None or decide is None or not decide(status, body):
            return False
        self.endpoint, self._custom_client = spare, spare.client
        self.update_config(model_id=spare.model_id)
        return True


class _KernelTool(AgentTool):
    def __init__(self, run: _Run, spec: LoopTool) -> None:
        super().__init__()
        self.run = run
        self.spec = spec

    @property
    def tool_name(self) -> str:
        return self.spec.name

    @property
    def tool_spec(self) -> Any:
        return {
            "name": self.spec.name,
            "description": self.spec.description,
            "inputSchema": {"json": self.spec.input_schema},
        }

    @property
    def tool_type(self) -> str:
        return "python"

    async def stream(self, tool_use: ToolUse, invocation_state: dict[str, Any], **kwargs: Any) -> ToolGenerator:
        run, call_id = self.run, str(tool_use["toolUseId"])
        arguments = cast(Json, dict(tool_use.get("input") or {}))
        ctx = CallContext(call_id, run.step, call_id in run.approved)
        run.events.append(ToolStarted(call_id, self.spec.name, arguments))
        if call_id in run.rejected:
            run.events.append(ToolEnded(call_id, True, run.rejected[call_id]))
            yield _result(call_id, False, run.rejected[call_id])
            return
        if not await self.spec.offered(ctx):
            run.held = UnofferedTool(self.spec.name)
            yield _result(call_id, False, "Not run.")
            return
        # Strands holds the tool until this event is read, so the kernel records the call as running before its body
        # updates it: a call shown only after it ran would reach the chat as two ends.
        yield ToolStreamEvent(tool_use, "started")
        try:
            said = await self.spec.call(ctx, arguments)
        except LoopPause as e:
            run.paused = (call_id, self.spec.name, arguments, e.reason)
            # Raises Strands' interrupt: the run stops here and resumes at this call (driver.run).
            ToolContext(
                tool_use=tool_use, agent=invocation_state["agent"], invocation_state=invocation_state
            ).interrupt(REVIEW, reason=e.reason)
            return
        except Exception as e:  # held and raised before the next request (module docstring)
            run.held = e
            yield _result(call_id, False, "Not run.")
            return
        ok = not (isinstance(said, dict) and set(cast(Json, said)) == {"error"})
        run.events.append(ToolEnded(call_id, ok, said))
        yield _result(call_id, True, said)


def _result(call_id: str, ok: bool, said: Any) -> ToolResultEvent:
    text = said if isinstance(said, str) else json.dumps(said, default=str)
    return ToolResultEvent({"toolUseId": call_id, "status": "success" if ok else "error", "content": [{"text": text}]})


class _Gate(HookProvider):
    """A gated call stops for a person before it runs. A refused one (`barred`) is not asked about: its body says
    why it does not run."""

    def __init__(self, run: _Run) -> None:
        self.run = run

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before)

    def before(self, event: BeforeToolCallEvent) -> None:
        run, use = self.run, event.tool_use
        spec = run.tools.get(use["name"])
        call_id = str(use["toolUseId"])
        if spec is None or not spec.gated or spec.barred() is not None:
            return
        arguments = cast(Json, dict(use.get("input") or {}))
        run.paused = (call_id, spec.name, arguments, None)
        # On the resumed run this returns the person's answer instead of stopping.
        answer = event.interrupt(APPROVAL)
        if answer == "approved":
            run.approved.add(call_id)
            return
        said = run.rejected.setdefault(call_id, str(answer))
        run.events.append(ToolStarted(call_id, spec.name, arguments))
        run.events.append(ToolEnded(call_id, True, said))
        event.cancel_tool = said


def _agent(model: OpenAIModel, run: _Run, messages: list[Json]) -> Agent:
    return Agent(
        model=model,
        messages=cast(Any, messages),
        tools=[_KernelTool(run, t) for t in run.tools.values()],
        hooks=[_Gate(run)],
        callback_handler=None,
        # The kernel keeps the whole history; Strands' default window would trim it.
        conversation_manager=NullConversationManager(),
        # Calls run one at a time, in the order the model asked, so each body sees the ones before it.
        tool_executor=SequentialToolExecutor(),
        retry_strategy=None,
    )


async def run(
    *,
    endpoint: ModelEndpoint,
    tools: list[LoopTool],
    instructions: Callable[[], str],
    history: list[Json],
    prompt: str | None,
    step_limit: Callable[[], int | None],
    params: Json,
    paused: bytes | None = None,
    decision: tuple[bool, str] | None = None,
    response_format: Json | None = None,
    check: Callable[[str], str | None] | None = None,
    exchanged: list[Json] | None = None,
) -> AsyncIterator[LoopEvent]:
    """One run of the loop: a new one from `history` and `prompt`, or the run `paused` wrote, resumed with the
    person's `decision` (approved, and the words the model is told on a rejection). Ends with LoopPaused or LoopDone.
    `check` names what is wrong with a final answer (its schema); the model gets one more try. `exchanged` is kept
    filled with the run's messages, so a caller still has them when the run raises."""
    kept = exchanged if exchanged is not None else []
    async for event in _run(
        endpoint,
        tools,
        instructions,
        history,
        prompt,
        step_limit,
        params,
        paused,
        decision,
        response_format,
        check,
        kept,
    ):
        yield event


async def _run(  # noqa: PLR0917 - run()'s keywords, passed on in order
    endpoint: ModelEndpoint,
    tools: list[LoopTool],
    instructions: Callable[[], str],
    history: list[Json],
    prompt: str | None,
    step_limit: Callable[[], int | None],
    params: Json,
    paused: bytes | None,
    decision: tuple[bool, str] | None,
    response_format: Json | None,
    check: Callable[[str], str | None] | None,
    exchanged: list[Json],
) -> AsyncIterator[LoopEvent]:
    loop = _Run(tools, step_limit)
    model = _GatewayModel(endpoint, loop, instructions, params, response_format)
    if paused is not None:
        stopped = decode(paused)
        agent = _agent(model, loop, [])
        agent.load_snapshot(Snapshot.from_dict(stopped.snapshot))
        approved, said = decision or (False, "")
        if approved:
            loop.approved.add(stopped.tool_call_id)
        else:
            loop.rejected[stopped.tool_call_id] = said
        asked: Any = [
            {"interruptResponse": {"interruptId": stopped.interrupt_id, "response": "approved" if approved else said}}
        ]
    else:
        agent = _agent(model, loop, copy.deepcopy(history))
        asked = prompt if prompt is not None else []
    try:
        async for event in _turns(agent, loop, asked, check):
            yield event
    finally:
        exchanged[:] = _messages(agent)


async def _turns(
    agent: Agent, loop: _Run, asked: Any, check: Callable[[str], str | None] | None
) -> AsyncIterator[LoopEvent]:
    tries = 2 if check is not None else 1
    for attempt in range(tries):
        text = ""
        result: Any = None
        try:
            async for event in agent.stream_async(asked):
                for queued in loop.events:
                    yield queued
                loop.events.clear()
                if chunk := event.get("data"):
                    text += str(chunk)
                    yield TextChunk(str(chunk))
                if "result" in event:
                    result = event["result"]
        except EventLoopException as e:
            # Strands wraps what a later cycle raised; the kernel ends the turn on the exception itself.
            cause = e.__cause__
            raise (cause if isinstance(cause, Exception) else e) from None
        for queued in loop.events:
            yield queued
        loop.events.clear()
        loop.raise_held()
        if result is not None and result.stop_reason == "interrupt" and loop.paused is not None:
            call_id, name, arguments, reason = loop.paused
            interrupt = result.interrupts[0].to_dict()
            snapshot = agent.take_snapshot(preset="session").to_dict()
            yield LoopPaused(
                call_id,
                name,
                arguments,
                reason,
                encode(PausedRun(snapshot, interrupt["id"], call_id)),
                _messages(agent),
            )
            return
        problem = check(text) if check is not None else None
        if problem is None:
            usage = cast(dict[str, int], result.metrics.accumulated_usage if result is not None else {})
            yield LoopDone(
                text,
                _messages(agent),
                int(usage.get("inputTokens", 0)),
                int(usage.get("outputTokens", 0)),
                loop.requests,
            )
            return
        if attempt + 1 == tries:
            raise SchemaMismatch(problem)
        asked = f"{problem}. Answer again, matching the schema."


async def close(
    *, endpoint: ModelEndpoint, system_prompt: str, messages: list[Json], prompt: str, purpose: str, params: Json
) -> str:
    """One tool-less request over a run's messages (the closing answer at the budget): its text."""
    loop = _Run([], lambda: 1)
    loop.purpose = purpose
    agent = _agent(_GatewayModel(endpoint, loop, lambda: system_prompt, params, None), loop, copy.deepcopy(messages))
    said = await agent.invoke_async(prompt)
    loop.raise_held()
    return str(said).strip()


def _messages(agent: Agent) -> list[Json]:
    return cast(list[Json], copy.deepcopy(list(agent.messages)))
