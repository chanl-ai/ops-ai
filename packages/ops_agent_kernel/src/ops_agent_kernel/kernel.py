"""One agent turn on Pydantic AI (spec 15 section 4, ADR-0014).

The library drives model steps; the kernel owns everything that crosses a boundary: context assembly, tool calls
through the executor port with idempotency keys, gated writes ending the turn as an `Interrupt`, and resuming from
one. The agent object is built per turn and holds no state between turns.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults, RunContext, Tool, ToolApproved, ToolDenied
from pydantic_ai.exceptions import ModelHTTPError, UsageLimitExceeded
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelResponse,
    PartDeltaEvent,
    PartStartEvent,
    RetryPromptPart,
    TextPart,
    TextPartDelta,
    ToolCallPart,
)
from pydantic_ai.run import AgentRunResultEvent
from pydantic_ai.usage import UsageLimits

from ops_service_kit.ids import action_id, input_hash

from .context import UnknownVariableError, assemble, cited_numbers
from .events import (
    CitationsReady,
    Interrupted,
    KernelEvent,
    StatusChanged,
    TextDelta,
    ToolInputAvailable,
    ToolOutput,
    TurnFinished,
)
from .ports import KernelPorts
from .types import (
    CitationRef,
    Interrupt,
    Passage,
    PendingCall,
    TokenUsage,
    ToolCallRecord,
    ToolGrant,
    TurnRequest,
    TurnResult,
)

KNOWLEDGE_K = 3


def refusal_code(body: object) -> str | None:
    """The `code` of a refusal body, whether the client kept the whole envelope or only its `error` member."""
    if not isinstance(body, dict):
        return None
    fields = cast(dict[str, Any], body)
    inner = fields.get("error")
    code = cast(dict[str, Any], inner).get("code") if isinstance(inner, dict) else fields.get("code")
    return str(code) if code else None


def _args(part: ToolCallPart) -> dict[str, Any]:
    return part.args_as_dict()


@dataclass
class _TurnState:
    req: TurnRequest
    grants: dict[str, ToolGrant]
    records: dict[str, ToolCallRecord] = field(default_factory=dict[str, ToolCallRecord])
    order: list[str] = field(default_factory=list[str])
    step: int = 0
    text: str = ""

    def record(self, tool_call_id: str, tool: str, arguments: dict[str, Any]) -> ToolCallRecord:
        """The record for a call, created on first sight. The tool function can run before its call event is
        read off the stream, so both paths go through here."""
        if tool_call_id in self.records:
            return self.records[tool_call_id]
        resume = self.req.resume
        pending = resume.interrupt.pending_call if resume else None
        if pending and pending.tool_call_id == tool_call_id:
            key = pending.key
        else:
            key = f"{self.req.run_id}:{self.req.turn_id}:{self.step}:{len(self.order)}"
        grant = self.grants[tool]
        rec = ToolCallRecord(
            tool_call_id=tool_call_id,
            key=key,
            tool=tool,
            server=grant.server,
            access=grant.access,
            input=arguments,
            input_hash=input_hash(arguments),
            status="running",
        )
        self.records[tool_call_id] = rec
        self.order.append(tool_call_id)
        return rec


def _tool(state: _TurnState, ports: KernelPorts, grant: ToolGrant) -> Tool[None]:
    resume = state.req.resume
    token = resume.approval_token if resume and resume.decision == "approved" else None

    async def call(ctx: RunContext[None], **arguments: Any) -> Any:
        rec = state.record(ctx.tool_call_id or f"call_{len(state.order)}", grant.name, arguments)
        started = time.monotonic()
        outcome = await ports.tools.execute(
            grant.name, arguments, key=rec.key, approval_token=token if grant.gated else None
        )
        rec.duration_ms = int((time.monotonic() - started) * 1000)
        rec.status = "ok" if outcome.ok else "error"
        rec.output = outcome.output
        rec.view = outcome.view
        # Errors go back to the model as information so it can explain or try other arguments (spec 15 4.2).
        return outcome.output if outcome.ok else {"error": outcome.output}

    tool = Tool[None].from_schema(
        cast(Callable[..., Awaitable[Any]], call), grant.name, grant.description, grant.input_schema, takes_ctx=True
    )
    # A write or money movement stops at a gate: the library ends the run with a deferred request (spec 15 5).
    tool.requires_approval = grant.gated
    return tool


async def _retrieve(req: TurnRequest, ports: KernelPorts) -> list[Passage]:
    if not req.kb_ids or not req.user_turn:
        return []
    return await ports.knowledge.search(req.user_turn, req.kb_ids, k=KNOWLEDGE_K)


def _interrupt(state: _TurnState, requests: DeferredToolRequests, history: list[ModelMessage]) -> Interrupt:
    part = requests.approvals[0]
    arguments = _args(part)
    rec = state.record(part.tool_call_id, part.tool_name, arguments)
    rec.status = "gated"
    pending = PendingCall(
        tool_call_id=part.tool_call_id,
        key=rec.key,
        action_id=action_id(rec.key),
        tool=rec.tool,
        server=rec.server,
        access=rec.access,
        input=arguments,
        input_hash=rec.input_hash,
    )
    return Interrupt(
        interrupt_id=rec.key,
        kind="approval",
        needed=f"Approval to run {rec.tool}",
        pending_call=pending,
        history=ModelMessagesTypeAdapter.dump_json(history),
    )


async def run_turn(req: TurnRequest, ports: KernelPorts) -> AsyncIterator[KernelEvent]:
    """Streams one turn's events, ending with exactly one `TurnFinished`."""
    state = _TurnState(req=req, grants={t.name: t for t in req.tools})
    tools = [_tool(state, ports, g) for g in sorted(req.tools, key=lambda t: t.name)]
    passages: list[Passage] = []
    digest: dict[str, str] = {}
    all_messages: list[ModelMessage] = []
    usage = TokenUsage()

    def finish(status: Literal["completed", "interrupted", "failed"], stop: str, **extra: Any) -> TurnFinished:
        records = [state.records[i] for i in state.order]
        answered = next((m.model_name for m in reversed(all_messages) if isinstance(m, ModelResponse)), None)
        cited = [CitationRef(n, passages[n - 1]) for n in cited_numbers(state.text) if 0 < n <= len(passages)]
        return TurnFinished(
            TurnResult(
                turn_id=req.turn_id,
                status=status,
                stop_reason=cast(Any, stop),
                text=state.text,
                tool_calls=records,
                citations=cited,
                context_digest=digest,
                model_name=answered,
                usage=usage,
                **extra,
            )
        )

    yield StatusChanged("thinking")
    try:
        if req.resume:
            history: list[ModelMessage] = ModelMessagesTypeAdapter.validate_json(req.resume.interrupt.history)
            call_id = req.resume.interrupt.pending_call.tool_call_id
            decision: ToolApproved | ToolDenied = (
                ToolApproved()
                if req.resume.decision == "approved"
                else ToolDenied(f"The reviewer rejected this action: {req.resume.reason or 'no reason given'}")
            )
            results = DeferredToolResults(approvals={call_id: decision})
            system_prompt, user_prompt = "\n\n".join(f.text for f in req.settings.instructions if f.stable), None
        else:
            if req.kb_ids and req.user_turn:
                yield StatusChanged("retrieving")
                passages = await _retrieve(req, ports)
            ctx = assemble(
                settings=req.settings,
                tools=req.tools,
                transcript=req.transcript,
                user_turn=req.user_turn or "",
                passages=passages,
                variables=req.variables,
            )
            digest = ctx.digest
            history, results, system_prompt, user_prompt = ctx.history, None, ctx.system_prompt, ctx.user_prompt
    except UnknownVariableError as e:
        yield finish("failed", "error", error=str(e))
        return

    model = ports.models.model_for(req.settings.model_alias) if ports.models is not None else ports.model
    agent = Agent[None, str | DeferredToolRequests](
        model,
        deps_type=type(None),
        output_type=[str, DeferredToolRequests],
        tools=tools,
        instructions=system_prompt,
    )
    limits = UsageLimits(request_limit=req.settings.max_steps, tool_calls_limit=req.settings.max_tool_calls)
    writing = False
    output: str | DeferredToolRequests | None = None
    try:
        async with asyncio.timeout(req.deadline_seconds):
            async with agent.run_stream_events(
                user_prompt, message_history=history, deferred_tool_results=results, usage_limits=limits
            ) as stream:
                async for event in stream:
                    if isinstance(event, PartStartEvent):
                        if event.index == 0:
                            state.step += 1
                        if isinstance(event.part, TextPart) and event.part.content:
                            if not writing:
                                writing = True
                                yield StatusChanged("writing")
                            state.text += event.part.content
                            yield TextDelta(event.part.content)
                    elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                        if not writing:
                            writing = True
                            yield StatusChanged("writing")
                        state.text += event.delta.content_delta
                        yield TextDelta(event.delta.content_delta)
                    elif isinstance(event, FunctionToolCallEvent):
                        writing = False
                        rec = state.record(event.part.tool_call_id, event.part.tool_name, _args(event.part))
                        yield StatusChanged("calling_tool")
                        yield ToolInputAvailable(rec)
                    elif isinstance(event, FunctionToolResultEvent):
                        rec = state.records.get(event.tool_call_id)
                        if rec is None:
                            continue
                        if isinstance(event.part, RetryPromptPart):
                            rec.status, rec.output = "error", event.part.model_response()
                        yield ToolOutput(rec)
                    elif isinstance(event, AgentRunResultEvent):
                        output = event.result.output
                        all_messages = event.result.all_messages()
                        u = event.result.usage
                        usage = TokenUsage(u.input_tokens, u.output_tokens, u.requests)
    except TimeoutError:
        yield finish(
            "failed",
            "deadline",
            error=f"The reply took longer than {int(req.deadline_seconds)} seconds and was stopped.",
        )
        return
    except UsageLimitExceeded:
        yield finish("completed", "max_tool_calls", error=None)
        return
    except ModelHTTPError as e:
        code = refusal_code(e.body)
        yield finish(
            "failed",
            "error",
            error=f"The model call was refused ({e.status_code} {code or 'error'}).",
            error_status=e.status_code,
            error_code=code,
        )
        return
    except Exception as e:  # The turn fails with its partial text kept; the caller reports it (spec 15 4.7).
        yield finish("failed", "error", error=f"The model call failed: {type(e).__name__}: {e}")
        return

    if isinstance(output, DeferredToolRequests) and output.approvals:
        interrupt = _interrupt(state, output, all_messages)
        rec = state.records[interrupt.pending_call.tool_call_id]
        yield ToolOutput(rec)
        yield Interrupted(interrupt)
        yield finish("interrupted", "interrupt", interrupt=interrupt)
        return

    done = finish(
        "completed", "final", no_answer=bool(req.kb_ids and req.user_turn and not passages and not state.order)
    )
    if done.result.citations:
        yield CitationsReady(done.result.citations)
    yield done
