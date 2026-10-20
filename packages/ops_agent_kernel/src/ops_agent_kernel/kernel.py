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

from jsonschema import Draft202012Validator
from pydantic_ai import (
    Agent,
    DeferredToolRequests,
    DeferredToolResults,
    ModelRetry,
    RunContext,
    Tool,
    ToolApproved,
    ToolDenied,
)
from pydantic_ai.exceptions import ApprovalRequired, ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded
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
from pydantic_ai.output import NativeOutput, StructuredDict
from pydantic_ai.run import AgentRunResultEvent
from pydantic_ai.usage import UsageLimits

from ops_service_kit.ids import action_id, input_hash

from . import guard, pii, present, search
from . import skills as skillset
from .context import UnknownVariableError, assemble, cited_numbers
from .events import (
    CitationsReady,
    Interrupted,
    KernelEvent,
    SkillLoaded,
    StatusChanged,
    TextDelta,
    TextReplaced,
    ToolInputAvailable,
    ToolOutput,
    TurnFinished,
)
from .ports import KernelPorts, KnowledgeUnavailableError
from .types import (
    CitationRef,
    Guardrail,
    Interrupt,
    Passage,
    PendingCall,
    Skill,
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
    # Calls that reached a granted tool this turn, against the agent's max_tool_calls (present is not one).
    granted_calls: int = 0
    # The last way the answer failed its output schema, for the error when the retries run out.
    schema_problem: str = ""
    # Skills in this turn, always-on first, and what each was loaded for (spec 11 5.3).
    loaded: list[Skill] = field(default_factory=list[Skill])
    # What a guardrail kept from the person, for the audit record (TurnResult.withheld).
    withheld: str = ""
    # What the person saw stream and a guardrail then replaced (TurnResult.retracted).
    retracted: str = ""
    # Text already sent as deltas this turn.
    shown_text: str = ""
    loads: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    # Widget parts present showed this turn, against the agent's widgets_per_turn (c-082).
    shown: int = 0
    # Set once present is refused for the cap: a further call ends the turn.
    present_closed: bool = False

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


def _present(state: _TurnState) -> Tool[None]:
    """The built-in present tool: a shaped part on the call record, no port behind it (present.py). An agent's widgets
    and composition widen it per turn (c-082); each shown part counts toward the agent's widgets per turn."""
    g = state.grants[present.NAME]
    cap = state.req.settings.widgets_per_turn

    async def call(ctx: RunContext[None], **arguments: Any) -> Any:
        rec = state.record(ctx.tool_call_id or f"call_{len(state.order)}", present.NAME, arguments)
        if state.present_closed:
            # The model was told to stop and called again: end the turn with what it has shown, so a model that
            # ignores the refusal cannot spend the rest of the step limit.
            rec.status, rec.output = "error", {"error": "Stopped: present was called again after the widget limit."}
            raise WidgetLimitReached("present was called again after the per-answer widget limit.")
        if cap is not None and state.shown >= cap:
            state.present_closed = True
            # Said as an instruction: a model told only the limit keeps retrying until the step limit ends the turn.
            why = f"This agent shows at most {cap} widgets in one answer. Do not call present again; answer in text."
            rec.status, rec.output = "error", {"error": why}
            return {"error": why}
        shown, said = present.run(arguments, state.req.settings, {t.name for t in state.req.tools})
        if shown is None:
            rec.status, rec.output = "error", {"error": said}
            return {"error": said}
        state.shown += 1
        rec.status, rec.output = "ok", {"presented": said}
        rec.view = {"part": shown}
        return {"presented": said}

    # Still offered after a refusal: a model that calls it again reaches `call`, which ends the turn. Withdrawing the
    # tool instead leaves the library answering "unknown tool" and the model retrying until the step limit.
    tool = Tool[None].from_schema(
        cast(Callable[..., Awaitable[Any]], call),
        present.NAME,
        g.description,
        g.input_schema,
        takes_ctx=True,
    )
    return tool


class WidgetLimitReached(UsageLimitExceeded):
    """present called after the per-answer widget limit refused it and was withdrawn (c-082). Ends the turn with the
    text and widgets it already has."""


class ToolLimitExceeded(UsageLimitExceeded):
    """The agent's tool-call budget, raised by the kernel itself. Any other UsageLimitExceeded is the library's
    request limit, which is the agent's step limit: the two end a turn for different reasons and say so differently."""


def _with_skills(system_prompt: str, pinned: list[Skill]) -> str:
    """Always-on skill bodies after the agent's instructions, then the index of on-match skills (spec 11 5.3)."""
    added = skillset.prompt(pinned)
    return f"{system_prompt}\n\n{added}" if added else system_prompt


def _withhold(state: _TurnState, guarded: bool) -> TextReplaced | None:
    """A guarded turn that ends any way but a passed check keeps none of its unchecked text in the stored message or
    the result. Text it streamed is cleared from the screen too (the TextReplaced to send); text it held was never
    shown."""
    if not guarded:
        return None
    if state.shown_text:
        state.retracted, state.shown_text, state.text = state.shown_text, "", ""
        return TextReplaced("")
    state.withheld, state.text = state.text, ""
    return None


def _replace(state: _TurnState, text: str) -> TextDelta | TextReplaced:
    """Sends `text` as the answer: a delta when nothing is on screen yet, else a replacement of what streamed."""
    shown = state.shown_text
    state.text = text
    if not shown:
        return TextDelta(text)
    state.retracted, state.shown_text = shown, text
    return TextReplaced(text)


def _fired(hit: guard.Hit, when: str) -> dict[str, Any]:
    r = hit.rule
    return {"guardrailId": r.guardrail_id, "version": r.version, "name": r.name, "topic": hit.topic, "when": when}


def _load_skill(state: _TurnState, grant: ToolGrant) -> Tool[None]:
    """The built-in load_skill tool: returns a pinned on-match skill's body, within the per-turn caps. No port behind
    it and, like present, not charged to the tool-call budget."""

    async def call(ctx: RunContext[None], **arguments: Any) -> Any:
        rec = state.record(ctx.tool_call_id or f"call_{len(state.order)}", skillset.NAME, arguments)
        skill, why = skillset.load(state.req.settings.skills, state.loaded, str(arguments.get("slug") or ""))
        if skill is None:
            rec.status, rec.output = "error", {"error": why}
            return {"error": why}
        if skill not in state.loaded:
            state.loaded.append(skill)
            state.loads.append(skillset.loaded_entry(skill, str(arguments.get("matched") or skill.use_when)))
        rec.status, rec.output = "ok", {"loaded": skill.slug, "version": skill.version}
        return {"skill": skill.name, "version": skill.version, "instructions": skill.instructions}

    return Tool[None].from_schema(
        cast(Callable[..., Awaitable[Any]], call), skillset.NAME, grant.description, grant.input_schema, takes_ctx=True
    )


def _search(state: _TurnState) -> Tool[None]:
    """The built-in search_tools tool over this turn's own offered tools (search.py); no port behind it, and like
    present it is not charged to the tool-call budget."""

    async def call(ctx: RunContext[None], **arguments: Any) -> Any:
        rec = state.record(ctx.tool_call_id or f"call_{len(state.order)}", search.NAME, arguments)
        found = search.search(state.req.tools, str(arguments.get("query") or ""))
        rec.status, rec.output = "ok", {"tools": found}
        return {"tools": found}

    return Tool[None].from_schema(
        cast(Callable[..., Awaitable[Any]], call),
        search.NAME,
        search.SEARCH.description,
        search.SEARCH.input_schema,
        takes_ctx=True,
    )


def _tool(state: _TurnState, ports: KernelPorts, grant: ToolGrant) -> Tool[None]:
    resume = state.req.resume
    token = resume.approval_token if resume and resume.decision == "approved" else None

    async def call(ctx: RunContext[None], **arguments: Any) -> Any:
        # The agent's tool-call budget counts the calls that reach a system; the built-in present tool reaches none
        # and is bounded by the step limit instead, so an agent with no tool calls can still answer with a widget.
        cap = state.req.settings.max_tool_calls
        if cap is not None and state.granted_calls >= cap:
            raise ToolLimitExceeded(f"The agent may make {cap} tool calls a reply.")
        state.granted_calls += 1
        rec = state.record(ctx.tool_call_id or f"call_{len(state.order)}", grant.name, arguments)
        started = time.monotonic()
        # A call a person approved carries the token: a gated write's, or one the gateway sent for review (c-300).
        approved = grant.gated or ctx.tool_call_approved
        outcome = await ports.tools.execute(
            grant.name, arguments, key=rec.key, approval_token=token if approved else None
        )
        if outcome.needs_review is not None and not ctx.tool_call_approved:
            # The gateway would not send it without a person: the turn pauses for approval with the reason.
            rec.status = "gated"
            raise ApprovalRequired(metadata={"reason": outcome.needs_review})
        rec.duration_ms = int((time.monotonic() - started) * 1000)
        rec.status = "ok" if outcome.ok else "error"
        rec.output = outcome.output
        rec.view = outcome.view
        # Errors go back to the model as information so it can explain or try other arguments (spec 15 4.2).
        return outcome.output if outcome.ok else {"error": outcome.output}

    tool = Tool[None].from_schema(
        cast(Callable[..., Awaitable[Any]], call), grant.name, grant.description, grant.input_schema, takes_ctx=True
    )
    # A write stops at a gate: the library ends the run with a deferred request (spec 15 5).
    tool.requires_approval = grant.gated
    return tool


async def _retrieve(req: TurnRequest, ports: KernelPorts) -> list[Passage]:
    if not req.kb_ids or not req.user_turn:
        return []
    return await ports.knowledge.search(req.user_turn, req.kb_ids, k=KNOWLEDGE_K)


def _reason(requests: DeferredToolRequests, call_id: str) -> str | None:
    """The reason a call raised for its approval (the gateway's check before sending), when it gave one."""
    meta = requests.metadata.get(call_id) or {}
    return str(meta["reason"]) if meta.get("reason") else None


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
        needed=f"Approval to run {rec.tool}" + (f": {why}" if (why := _reason(requests, part.tool_call_id)) else ""),
        pending_call=pending,
        history=ModelMessagesTypeAdapter.dump_json(history),
        loaded_skills=[e for s, e in zip(state.loaded, state.loads, strict=True) if s.loading == "on_match"],
    )


GUARDRAIL_UNAVAILABLE = (
    "I could not check this question against this agent's guardrails just now, so I have not answered it. Try again "
    "shortly."
)
TOOL_LIMIT_REACHED = (
    "I reached the most tool calls this agent may make in one reply before I could answer. Ask again, or narrow the "
    "question."
)
STEP_LIMIT_REACHED = "I reached the step limit for one reply before I could answer. Ask again, or narrow the question."
# Appended when a limit stops a turn that had already written part of its answer, so a partial reply never reads as
# a complete one.
CUT_SHORT_TOOLS = "\n\n(Reply cut short: the agent reached the most tool calls it may make in one reply.)"
CUT_SHORT_STEPS = "\n\n(Reply cut short: the agent reached its step limit for one reply.)"
KNOWLEDGE_UNAVAILABLE = (
    "The knowledge service is not available right now, so I cannot answer from the knowledge bases. Try again shortly."
)
KNOWLEDGE_WITHDRAWN = (
    "The knowledge this conversation searches is no longer available to this agent, so I cannot answer from it. "
    "Start a new conversation, or ask the agent's owner to grant the knowledge base again."
)


async def run_turn(req: TurnRequest, ports: KernelPorts) -> AsyncIterator[KernelEvent]:
    """Streams one turn's events, ending with exactly one `TurnFinished`. With the agent's redactPii on (c-293), what
    the turn shows and returns has personal data masked (pii.py); what the model reads, and the history a pause keeps,
    are not."""
    if not req.settings.redact_pii:
        async for event in _turn(req, ports):
            yield event
        return
    stream = pii.StreamMasker()
    async for event in _turn(req, ports):
        if isinstance(event, TextDelta):
            if shown := stream.push(event.delta):
                yield TextDelta(shown)
            continue
        if isinstance(event, TextReplaced):
            stream.reset()
            yield TextReplaced(pii.mask(event.text))
            continue
        # Text held back is released before anything that follows it in the stream.
        if rest := stream.flush():
            yield TextDelta(rest)
        if isinstance(event, ToolInputAvailable):
            yield ToolInputAvailable(pii.masked_call(event.call))
        elif isinstance(event, ToolOutput):
            yield ToolOutput(pii.masked_call(event.call))
        elif isinstance(event, CitationsReady):
            yield CitationsReady(pii.masked_citations(event.citations))
        elif isinstance(event, TurnFinished):
            yield TurnFinished(pii.masked_result(event.result))
        else:
            yield event


async def _turn(req: TurnRequest, ports: KernelPorts) -> AsyncIterator[KernelEvent]:
    """One turn's events as the model's loop produces them."""
    # Every turn may present a shaped answer (a comparison table) without a tool behind it (c-055 T021). A structured
    # call with no tools (memory extraction, a workflow's AI step) answers with its schema's JSON only, so it is offered
    # nothing to call.
    builtins = bool(req.tools) or req.output_schema is None
    state = _TurnState(
        req=req,
        grants={
            **{t.name: t for t in req.tools},
            **({present.NAME: present.grant(req.settings), search.NAME: search.SEARCH} if builtins else {}),
        },
    )
    tools = [_tool(state, ports, g) for g in sorted(req.tools, key=lambda t: t.name)] + (
        [_present(state), _search(state)] if builtins else []
    )
    if (load_grant := skillset.grant(req.settings.skills)) is not None:
        state.grants[skillset.NAME] = load_grant
        tools.append(_load_skill(state, load_grant))
    for s in req.settings.skills:
        if s.loading == "always":
            state.loaded.append(s)
            state.loads.append(skillset.loaded_entry(s, skillset.ALWAYS))
    # A resumed turn keeps the on-match skills it loaded before the pause (already journalled, so not loaded again).
    restored = 0
    for entry in req.resume.interrupt.loaded_skills if req.resume else []:
        skill = next(
            (s for s in req.settings.skills if s.skill_id == entry["skillId"] and s.version == entry["version"]), None
        )
        if skill is not None and skill not in state.loaded:
            state.loaded.append(skill)
            state.loads.append(entry)
            restored += 1
    passages: list[Passage] = []
    digest: dict[str, str] = {}
    all_messages: list[ModelMessage] = []
    usage = TokenUsage()

    # Filled once the turn's rules are known; a turn that ends before then checked none.
    checked: list[Guardrail] = []

    def ref(g: Guardrail) -> dict[str, Any]:
        return {"guardrailId": g.guardrail_id, "version": g.version, "name": g.name}

    def finish(status: Literal["completed", "interrupted", "failed"], stop: str, **extra: Any) -> TurnFinished:
        if status == "completed" and req.output_schema is not None and extra.get("output") is None:
            # A step asked for structured output and the turn ended without it: a refusal, knowledge withdrawn or out
            # of reach, a step limit. The caller needs a failure with the reason the turn gave, never a completed turn
            # whose output is nothing (a workflow step would take its ok port with null).
            reason = extra.get("error") or state.text or f"The turn ended ({stop}) without an answer."
            status, stop, extra = "failed", "no_output", {**extra, "error": reason, "error_code": "no_output"}
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
                skills=list(state.loads),
                withheld=state.withheld or None,
                retracted=state.retracted or None,
                guardrails_checked=[ref(g) for g in dict.fromkeys(checked)],
                guardrails_off=[ref(g) for g in req.settings.guardrails_off],
                **extra,
            )
        )

    if req.knowledge_withdrawn and not req.resume:
        state.text = KNOWLEDGE_WITHDRAWN
        yield TextDelta(KNOWLEDGE_WITHDRAWN)
        yield finish("completed", "final", no_answer=True)
        return
    # Always-on skills are loaded from the start, so their guardrails are checked on the question too. An agent
    # whose skills carry guardrails is guarded even before one loads: its answer is never streamed.
    rules = [*req.settings.guardrails, *(g for s in state.loaded for g in skillset.guardrails_of(s))]
    guarded = bool(rules) or any(s.guardrails for s in req.settings.skills)
    # A guarded answer streams as it is written and is replaced if its after-answer check fails, unless a rule known at
    # the start holds it until checked. A skill loaded mid-turn cannot hold: its guardrails never do (skills.py).
    streaming = not guarded or not any(r.hold for r in rules)
    checked.extend(rules)
    model = ports.models.model_for(req.settings.model_alias) if ports.models is not None else ports.model
    guard_model = guard.model_for(ports.models, model)
    if rules and req.user_turn and not req.resume:
        # A question about a blocked topic gets the guardrail's message; the answering model is never called.
        try:
            hit = await guard.check(guard_model, rules, req.user_turn)
        except guard.GuardrailUnavailable as e:
            state.text = GUARDRAIL_UNAVAILABLE
            yield TextDelta(GUARDRAIL_UNAVAILABLE)
            yield finish("failed", "guardrail_unavailable", error=str(e), error_code="guardrail_unavailable")
            return
        if hit is not None:
            state.text = hit.rule.message
            yield TextDelta(hit.rule.message)
            yield finish("completed", "guardrail", guardrail=_fired(hit, "before"))
            return
    # A resumed turn journalled its loads before the pause.
    for entry in [] if req.resume else state.loads:
        yield SkillLoaded(entry["skillId"], entry["version"], entry["name"], entry["matched"])
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
            system_prompt = _with_skills(system_prompt, req.settings.skills)
        else:
            if req.kb_ids and req.user_turn:
                yield StatusChanged("retrieving")
                try:
                    passages = await _retrieve(req, ports)
                except KnowledgeUnavailableError:
                    # Asked for knowledge, the turn says it is unavailable; otherwise it goes on without passages
                    # (a tool call or a plain answer needs none).
                    if req.knowledge_asked is not False:
                        state.text = KNOWLEDGE_UNAVAILABLE
                        yield TextDelta(KNOWLEDGE_UNAVAILABLE)
                        yield finish("completed", "final", no_answer=True)
                        return
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
            system_prompt = _with_skills(system_prompt, req.settings.skills)
    except UnknownVariableError as e:
        yield finish("failed", "error", error=str(e))
        return

    # With a schema the answer is the provider's native structured output (a json_schema response format): the model
    # may call tools, then its final message must match the schema, with no separate answer tool to call or skip.
    # Free text is then not an answer. Deferred requests stay possible, so a gated write still stops for review.
    answer_type: Any = (
        NativeOutput(
            StructuredDict(req.output_schema, name="final_result", description="The step's answer, matching its schema")
        )
        if req.output_schema is not None
        else str
    )
    agent = Agent[None, Any](
        model,
        deps_type=type(None),
        output_type=[answer_type, DeferredToolRequests],
        tools=tools,
        instructions=system_prompt,
    )
    if req.output_schema is not None:
        # The output tool carries the schema to the model but does not hold the answer to it; this does. A mismatch
        # goes back to the model once (pydantic-ai's retry), then ends the turn with schema_error.
        check = Draft202012Validator(req.output_schema)

        @agent.output_validator
        def _matches_schema(output: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
            if isinstance(output, DeferredToolRequests):
                return output
            found: list[Any] = list(check.iter_errors(output))  # pyright: ignore[reportUnknownMemberType]
            problems = sorted(found, key=lambda e: [str(p) for p in e.absolute_path])
            if problems:
                where = "/".join(str(p) for p in problems[0].absolute_path) or "the answer"
                state.schema_problem = f"{where}: {problems[0].message}"
                raise ModelRetry(f"{state.schema_problem}. Answer again, matching the schema.")
            return output

    limits = UsageLimits(request_limit=req.settings.max_steps)
    writing = False
    output: Any = None
    try:
        async with asyncio.timeout(req.deadline_seconds):
            async with agent.run_stream_events(
                user_prompt,
                message_history=history,
                deferred_tool_results=results,
                usage_limits=limits,
                model_settings={"temperature": req.settings.temperature}
                if req.settings.temperature is not None
                else None,
            ) as stream:
                async for event in stream:
                    if isinstance(event, PartStartEvent):
                        if event.index == 0:
                            state.step += 1
                        if isinstance(event.part, TextPart) and event.part.content:
                            if not writing:
                                writing = True
                                yield StatusChanged("writing" if streaming else "checking")
                            state.text += event.part.content
                            if streaming:
                                state.shown_text += event.part.content
                                yield TextDelta(event.part.content)
                    elif isinstance(event, PartDeltaEvent) and isinstance(event.delta, TextPartDelta):
                        if not writing:
                            writing = True
                            yield StatusChanged("writing" if streaming else "checking")
                        state.text += event.delta.content_delta
                        if streaming:
                            state.shown_text += event.delta.content_delta
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
        if (cleared := _withhold(state, guarded)) is not None:
            yield cleared
        yield finish(
            "failed",
            "deadline",
            error=f"The reply took longer than {int(req.deadline_seconds)} seconds and was stopped.",
        )
        return
    except WidgetLimitReached:
        if (cleared := _withhold(state, guarded)) is not None:
            yield cleared
        if not state.text and not state.shown:
            state.text = STEP_LIMIT_REACHED
            yield TextDelta(STEP_LIMIT_REACHED)
        yield finish("completed", "final", error=None)
        return
    except UsageLimitExceeded as e:
        tools = isinstance(e, ToolLimitExceeded)
        if (cleared := _withhold(state, guarded)) is not None:
            yield cleared
        # Stopped before writing anything: say why, never an empty reply. Stopped mid-answer: say it was cut short,
        # never a partial reply that reads as a complete one.
        notice = (
            (TOOL_LIMIT_REACHED if tools else STEP_LIMIT_REACHED)
            if not state.text
            else (CUT_SHORT_TOOLS if tools else CUT_SHORT_STEPS)
        )
        state.text += notice
        yield TextDelta(notice)
        yield finish("completed", "max_tool_calls" if tools else "max_steps", error=None)
        return
    except UnexpectedModelBehavior as e:
        if (cleared := _withhold(state, guarded)) is not None:
            yield cleared
        if req.output_schema is None:
            yield finish("failed", "error", error=f"The model call failed: {type(e).__name__}: {e}")
            return
        # The model did not return output matching the step's schema: a failure any caller sees (a workflow step's
        # error port, a chat turn), never a completed turn without its output.
        yield finish(
            "failed",
            "schema_error",
            error=f"The answer did not match the step's output schema: {state.schema_problem or e}",
            error_code="schema_error",
        )
        return
    except ModelHTTPError as e:
        if (cleared := _withhold(state, guarded)) is not None:
            yield cleared
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
        if (cleared := _withhold(state, guarded)) is not None:
            yield cleared
        yield finish("failed", "error", error=f"The model call failed: {type(e).__name__}: {e}")
        return

    if isinstance(output, DeferredToolRequests) and output.approvals:
        if (cleared := _withhold(state, guarded)) is not None:
            yield cleared
        interrupt = _interrupt(state, output, all_messages)
        rec = state.records[interrupt.pending_call.tool_call_id]
        yield ToolOutput(rec)
        yield Interrupted(interrupt)
        yield finish("interrupted", "interrupt", interrupt=interrupt)
        return

    fired: dict[str, Any] | None = None
    noted: dict[str, Any] | None = None
    # Skills loaded during the reply add their guardrails to the check of the answer.
    always_count = sum(1 for s in req.settings.skills if s.loading == "always")
    for s in state.loaded[always_count:]:
        rules.extend(skillset.guardrails_of(s))
        # The answer is checked against them, so the turn records them as checked.
        checked.extend(skillset.guardrails_of(s))
    for entry in state.loads[always_count + restored :]:
        yield SkillLoaded(entry["skillId"], entry["version"], entry["name"], entry["matched"])
    if guarded and state.text:
        # A guarded answer is checked once complete when any rule applies; an agent guarded only by a skill that never
        # loaded, or whose pins are all off, has none. A held answer is sent here whole after its check; a streamed one
        # is already on screen and is replaced only when the check changes it.
        if rules:
            # A hit gets one correction from a tool-less agent (a correction never runs a tool or opens an approval)
            # and, if that still hits or fails in any way, the guardrail's message.
            if streaming:
                yield StatusChanged("checking")
            try:
                hit = await guard.check(guard_model, rules, state.text)
            except guard.GuardrailUnavailable as e:
                yield _replace(state, GUARDRAIL_UNAVAILABLE)
                yield finish("failed", "guardrail_unavailable", error=str(e), error_code="guardrail_unavailable")
                return
            if hit is not None:
                if not state.shown_text:
                    state.withheld = state.text
                corrected = ""
                try:
                    fixer = Agent[None, str](model, deps_type=type(None), output_type=str, instructions=system_prompt)
                    again = await fixer.run(
                        f"Your answer touched a blocked topic ({hit.topic}). Answer the question again without it, "
                        "using only what you already found.",
                        message_history=all_messages,
                        usage_limits=UsageLimits(request_limit=1),
                    )
                    corrected = again.output.strip()
                except Exception:  # a correction that fails leaves only the refusal as safe to send
                    corrected = ""
                still = hit
                if corrected:
                    # A re-check that cannot run fails the turn closed, as the first check does, rather than passing
                    # for a hit.
                    try:
                        still = await guard.check(guard_model, rules, corrected)
                    except guard.GuardrailUnavailable as e:
                        yield _replace(state, GUARDRAIL_UNAVAILABLE)
                        yield finish(
                            "failed", "guardrail_unavailable", error=str(e), error_code="guardrail_unavailable"
                        )
                        return
                if still is not None:
                    state.text, fired = still.rule.message, _fired(still, "after")
                else:
                    state.text, noted = corrected, _fired(hit, "corrected")
        if not state.shown_text:
            yield TextDelta(state.text)
        elif state.text != state.shown_text:
            yield _replace(state, state.text)
        if fired is not None:
            yield finish("completed", "guardrail", guardrail=fired)
            return

    asked = req.knowledge_asked if req.knowledge_asked is not None else bool(req.kb_ids)
    structured: dict[str, Any] = {"output": output} if req.output_schema is not None else {}
    if noted is not None:
        structured["guardrail"] = noted
    done = finish(
        "completed",
        "final",
        no_answer=bool(asked and req.user_turn and not passages and not state.order),
        **structured,
    )
    if done.result.citations:
        yield CitationsReady(done.result.citations)
    yield done
