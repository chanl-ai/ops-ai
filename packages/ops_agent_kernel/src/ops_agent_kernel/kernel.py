"""One agent turn on Pydantic AI (spec 15 section 4, ADR-0014).

The library drives model steps; the kernel owns everything that crosses a boundary: context assembly, tool calls
through the executor port with idempotency keys, gated writes ending the turn as an `Interrupt`, and resuming from
one. The agent object is built per turn and holds no state between turns.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, replace
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
from pydantic_ai.capabilities import ToolSearch
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
from pydantic_ai.settings import ModelSettings
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.usage import UsageLimits

from ops_contracts.skill_run import SkillRunState, grant_token
from ops_service_kit.http import Json, JsonList, JsonValue
from ops_service_kit.ids import action_id, input_hash
from ops_service_kit.narrow import json_object

from . import answer_check, guard, judge, pii, present, prompt_writer, search, step_tools, steps, tool_cache
from . import plan as planner
from . import skills as skillset
from .context import UnknownVariableError, assemble, cited_numbers
from .events import (
    CitationsReady,
    Interrupted,
    KernelEvent,
    SkillRunChanged,
    StatusChanged,
    TextDelta,
    TextReplaced,
    ToolInputAvailable,
    ToolOutput,
    TurnFinished,
)
from .ports import BudgetReachedError, KernelPorts, KnowledgeUnavailableError, finishing
from .types import (
    BaseAnswer,
    CitationRef,
    Guardrail,
    GuardrailFired,
    GuardrailRef,
    Interrupt,
    LoadedSkill,
    Passage,
    PendingCall,
    Plan,
    Skill,
    TokenUsage,
    ToolCallRecord,
    ToolGrant,
    TurnRequest,
    TurnResult,
)

# The built-in tool that searches knowledge bases; the kernel narrows it to the turn's own bases (_own_knowledge).
SEARCH_KNOWLEDGE = "search_knowledge"
# The search_knowledge argument that asks for every base of the team; set by the kernel only (_own_knowledge).
ALL_TEAM = "allTeamKnowledgeBases"
NO_OWN_KNOWLEDGE = "This agent has no knowledge bases to search; answer from the other tools, or say it is not known."


# The server a call to a name outside the agent's grants is recorded under: it reached none.
UNGRANTED = "none"
# The kernel's own tools: they reach no system, so they say nothing about whether a read succeeded.
KERNEL_TOOLS = (present.NAME, search.NAME, skillset.NAME, planner.NAME, *step_tools.NAMES)


def refusal_code(body: object) -> str | None:
    """The `code` of a refusal body, whether the client kept the whole envelope or only its `error` member."""
    return _refusal_field(body, "code")


def refusal_text(status: int, body: object) -> str:
    """What a person reads for a refused model call: the message models-service wrote for its code, which says what
    happened and what to do. Its envelope always carries a code; a body without one (a proxy's page, or a gateway's
    JSON with only a message) is never shown, only the status."""
    code = refusal_code(body)
    said = _refusal_field(body, "message") if code else None
    return said or f"The model call was refused ({status} {code or 'error'})."


def _refusal_field(body: object, name: str) -> str | None:
    fields = json_object(body)
    inner = fields.get("error")
    value = inner.get(name) if isinstance(inner, dict) else fields.get(name)
    return str(value) if value else None


def _args(part: ToolCallPart) -> Json:
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
    loads: list[LoadedSkill] = field(default_factory=list[LoadedSkill])
    # How each of `loads` entered the reply (picked, carried, loaded, always), in the same order: told in the journal
    # event, kept out of the result's entries.
    hows: list[str] = field(default_factory=list[str])
    # Skills an earlier turn of the conversation loaded, kept loaded here outside this turn's load caps.
    carried: list[Skill] = field(default_factory=list[Skill])
    # Widget parts present showed this turn, against the agent's widgets_per_turn.
    shown: int = 0
    # Set once present is refused for the cap: a further call ends the turn.
    # The model step on which present was refused at the widget cap; None until then.
    present_closed: int | None = None
    # Set when the model repeats a call it already made this reply: it is offered no system tool after that.
    tools_closed: bool = False
    # The step whose calls past max_tool_calls were told to stop and answer; a call in a later step ends the turn.
    cap_told_step: int | None = None
    # The turn's plan (plan.py) as the last accepted call left it, how many times it was replaced, and the call that
    # drew it, whose part each change redraws.
    plan: Plan | None = None
    replans: int = 0
    plan_call: str | None = None
    # The model steps (state.step) whose calls to a system succeeded: the plan ticks once each such step ends.
    read_steps: set[int] = field(default_factory=set[int])
    # The loop's request limit, raised by max_steps each time a plan step is done, and the step count it stands at.
    limits: UsageLimits | None = None
    step_limit: int = 0
    # Calls to the kernel's own tools this turn, against the agent's max_builtin_calls; set once one is refused.
    builtin_calls: int = 0
    builtins_refused: int | None = None
    # Passages: the knowledge block's, then each a tool returned (search_knowledge), numbered on from the block's, so
    # the reply cites either with [n] and the chat draws each as a citation.
    passages: list[Passage] = field(default_factory=list[Passage])
    # The calls whose result brought passages: a turn that read only these answers from knowledge and cites it.
    passage_calls: set[str] = field(default_factory=set[str])
    # Each searched base's answer settings by id, in search order, from the knowledge block and search_knowledge.
    kb_answers: dict[str, BaseAnswer] = field(default_factory=dict[str, BaseAnswer])
    # Calls being made now, by (tool, input hash): the same call made twice in one step waits for the first.
    inflight: dict[tuple[str, str], asyncio.Event] = field(default_factory=dict[tuple[str, str], asyncio.Event])
    # How many of `loads` were journalled before this turn's own loads (kept at a pause, or carried from a reply).
    restored: int = 0
    # The running-skill record (steps.py) as it stands, the agent's skills that run step by step, and whether the turn
    # returns a record at all: an agent with no such skill and no record carried returns none.
    run: SkillRunState = field(default_factory=SkillRunState)
    stepped: list[Skill] = field(default_factory=list[Skill])
    tracks: bool = False
    # Skills with steps this turn started, whose guardrails join the check of the answer.
    started: list[Skill] = field(default_factory=list[Skill])
    # Calls to the step tools this turn, against step_tools.limit.
    step_calls: int = 0
    # The model steps in which the current skill step's tool result was checked: two calls of that tool in one model
    # step move the record once and count as one attempt.
    judged: set[int] = field(default_factory=set[int])
    # Events a tool call raised, sent once the stream reaches its result.
    events: list[KernelEvent] = field(default_factory=list[KernelEvent])
    # By skill id, the step tools of a skill this reply stopped any way but done or switched (steps.held): not offered
    # for the rest of the reply, even as the current step's tool of another skill, unless that skill starts again
    # (which only a skill the model itself exited can: steps.final).
    held: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    # The tools reachable only as a step of a skill, with the slugs of the skills that own each (steps.owned).
    owned: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    # What the model is told when a skill picked from the menu did not start for want of an input it requires.
    unstarted: str = ""
    # The model that decides a step's sentence check (judge.model_for), and the tokens its calls spent this turn,
    # added to the turn's usage where it finishes.
    judge_model: Any = None
    judge_spent: TokenUsage = field(default_factory=TokenUsage)

    def drop_carried(self) -> None:
        """A skill loaded or started in this reply takes the place of the ones carried from earlier replies: one
        on-match skill is carried at a time, and none beside a skill with steps."""
        for skill in self.carried:
            i = self.loaded.index(skill)
            del self.loaded[i], self.loads[i], self.hows[i]
            self.restored -= 1
        self.carried.clear()

    def moved(self, run: SkillRunState) -> str | None:
        """The running-skill record after a step tool or a step's tool result changed it. When the step it lands on
        calls a tool a skill stopped in this reply holds, the skill ends there, and what the model is told instead
        is returned."""
        if (stopped := steps.held(self.run, run)) is not None:
            self.held[stopped[0]] = stopped[1]
        if run.running is not None:
            self.held.pop(run.running.skill_id, None)
        if (halted := steps.halted(run, self.stepped, self.held)) is not None:
            run = halted.run
        was, self.run, now = self.run.running, run, run.running
        self.events.append(SkillRunChanged(run.model_copy(deep=True)))
        if now is None or (was is not None and (was.skill_id, was.version) == (now.skill_id, now.version)):
            return halted.said if halted is not None else None
        self.drop_carried()
        skill = next((s for s in self.stepped if (s.skill_id, s.version) == (now.skill_id, now.version)), None)
        if skill is not None:
            self.started.append(skill)
            entry = skillset.loaded_entry(skill, skill.use_when, now.inputs)
            self.events.append(skillset.event(entry, "started"))
        return None

    def barred(self, tool: str) -> str | None:
        """Why a granted tool may not be offered, found by search or called now (steps.barred); None when it may.
        Knowledge search stays open beside a step's own tool when the turn has knowledge to search."""
        knowledge = bool(self.req.kb_ids or self.req.all_team_knowledge)
        return steps.barred(
            self.run,
            self.stepped,
            tool,
            owned=self.owned,
            stopped=self.held,
            always=(SEARCH_KNOWLEDGE,) if knowledge else (),
        )

    def free(self) -> bool:
        """No step names a tool to call now. While one does, the model is offered that tool and nothing to plan,
        search or load with."""
        return steps.target(self.run) is None

    def position(self) -> tuple[str, int] | None:
        """The skill and step the record is on (the sub-skill's while one runs)."""
        r = self.run.running
        if r is None:
            return None
        return (r.sub.skill_id, r.sub.step) if r.sub is not None else (r.skill_id, r.step)

    async def step_result(self, run_step: int, at: tuple[str, int] | None, output: JsonValue, ok: bool) -> str | None:
        """Checks a result of the current step's tool and moves the record; what the model is told, or None when
        the call was not that step's (`at` is where the record stood when the call started). A sentence check is
        decided by the judge on the result as the tool returned it."""
        if at is None or self.position() != at or run_step in self.judged:
            return None
        self.judged.add(run_step)
        moved = steps.on_result(self.run, self.stepped, output, ok)
        said = self.moved(moved.run) or moved.said
        return await self.judge(output) or said

    async def judge(self, raw: JsonValue | None = None) -> str | None:
        """Asks the judge when the current step's sentence waits for a verdict (steps.to_judge) and moves the record
        on it; what the model is told, or None when no step waits. The judge is given the sentence and the evidence
        only: the step's result (`raw`, as the tool returned it, when given) and the skill's inputs, or for a step
        with no tool what the person wrote and the tools returned in this reply. Never the agent's instructions."""
        waiting = steps.to_judge(self.run)
        if waiting is None:
            return None
        at = self.position()
        verdict = await judge.verdict(self.judge_model, waiting.check, self._evidence(waiting, raw))
        u = self.judge_spent
        self.judge_spent = TokenUsage(
            u.input_tokens + verdict.usage.input_tokens,
            u.output_tokens + verdict.usage.output_tokens,
            u.requests + verdict.usage.requests,
        )
        if self.position() != at or steps.to_judge(self.run) != waiting:
            # Another call of the same model step moved the record while the judge answered.
            return None
        moved = steps.decided(self.run, self.stepped, verdict.passed, verdict.reason)
        return self.moved(moved.run) or moved.said

    def _evidence(self, waiting: steps.Judging, raw: JsonValue | None) -> str:
        inputs = f"\n\nThe skill's inputs: {json.dumps(waiting.inputs)}" if waiting.inputs else ""
        if not waiting.from_reply:
            value = raw if raw is not None else waiting.value
            return f"The step's result: {json.dumps(value, default=str)}{inputs}"
        returned = [
            f"- {r.tool}: {json.dumps(r.output, default=str)}"
            for r in (self.records[i] for i in self.order)
            if r.status == "ok" and r.tool not in step_tools.NAMES
        ]
        tools = "\n\nThe tools returned in this reply:\n" + "\n".join(returned) if returned else ""
        return f"The person wrote: {self.req.user_turn or ''}{tools}{inputs}"

    def last_step(self, step: int) -> bool:
        """The last step of a turn offers no tool, so the turn always keeps a step to answer in. A turn of one step
        is all last step: no later step could read a tool's result, so it answers from what it was given."""
        steps = self.step_limit or self.req.settings.max_steps
        return step >= steps

    def offered(self, ctx: RunContext[None], *, builtin: bool) -> bool:
        """Whether a tool is offered on the step about to run; `ctx.run_step` is that step's number."""
        return not self.last_step(ctx.run_step) and (builtin or not self.tools_closed)

    def charge_builtin(self, run_step: int) -> str | None:
        """Counts one call to a kernel tool made on model step `run_step`. Past the cap a call gets the instruction to
        answer in text; a call on a later step, after the model has read that, ends the turn, as present's widget cap
        does. Calls a model makes together in one response are all on one step, so each past the cap is told and none
        ends the turn. They stay offered: a withdrawn tool leaves the library answering "unknown tool" and the model
        retrying until the turn fails."""
        cap = self.req.settings.max_builtin_calls
        if cap is not None and self.builtin_calls >= cap:
            if told_before(self.builtins_refused, run_step):
                raise BuiltinLimitReached(f"A kernel tool was called again after the limit of {cap} a turn.")
            if self.builtins_refused is None:
                self.builtins_refused = run_step
            return BUILTIN_LIMIT.format(cap=cap)
        self.builtin_calls += 1
        return None

    def record(self, tool_call_id: str, tool: str, arguments: Json) -> ToolCallRecord:
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
        # A name the agent is not granted (guessed, or a deferred tool not yet found) is recorded with no server; the
        # model gets pydantic-ai's retry and nothing is sent anywhere.
        grant = self.grants.get(tool)
        rec = ToolCallRecord(
            tool_call_id=tool_call_id,
            key=key,
            tool=tool,
            server=grant.server if grant else UNGRANTED,
            access=grant.access if grant else "read",
            input=arguments,
            input_hash=input_hash(arguments),
            status="running",
        )
        self.records[tool_call_id] = rec
        self.order.append(tool_call_id)
        return rec


# What the model is told with a tool result the person already sees drawn, so it does not present it again.
SHOWN = (
    "The person sees this result as a table or card drawn with this step. Do not call present for it, and do not say "
    "where it is (above or below); answer in text."
)


def _present(state: _TurnState) -> Tool[None]:
    """The built-in present tool: a shaped part on the call record, no port behind it (present.py). An agent's widgets
    and composition widen it per turn; each shown part counts toward the agent's widgets per turn."""
    g = state.grants[present.NAME]
    cap = state.req.settings.widgets_per_turn

    async def call(ctx: RunContext[None], **arguments: Any) -> Any:
        rec = state.record(ctx.tool_call_id or f"call_{len(state.order)}", present.NAME, arguments)
        if (over := state.charge_builtin(ctx.run_step)) is not None:
            rec.status, rec.output = "error", {"error": over}
            return {"error": over}
        if told_before(state.present_closed, ctx.run_step):
            # The model was told to stop and called again: end the turn with what it has shown, so a model that
            # ignores the refusal cannot spend the rest of the step limit.
            rec.status, rec.output = "error", {"error": "Stopped: present was called again after the widget limit."}
            raise WidgetLimitReached("present was called again after the per-answer widget limit.")
        if cap is not None and state.shown >= cap:
            if state.present_closed is None:
                state.present_closed = ctx.run_step
            # Said as an instruction: a model told only the limit keeps retrying until the step limit ends the turn.
            why = f"This agent shows at most {cap} widgets in one answer. Do not call present again; answer in text."
            rec.status, rec.output = "error", {"error": why}
            return {"error": why}
        replies, refused = present.follow_ups(arguments)
        if refused is not None:
            rec.status, rec.output = "error", {"error": refused}
            return {"error": refused}
        rest = {k: v for k, v in arguments.items() if k != "followUps"}
        if replies is not None and not ({"shape", "kind", "widget", "layout", "data"} & set(rest)):
            # Quick replies alone: nothing is drawn but the chips under the reply.
            rec.status, rec.output, rec.view = "ok", {"offered": replies}, {"followUps": [*replies]}
            return {"offered": replies}
        shown, said = present.run(rest, state.req.settings, {t.name for t in state.req.tools})
        if shown is None:
            rec.status, rec.output = "error", {"error": said}
            return {"error": said}
        drawn = [p for r in state.records.values() if isinstance(p := (r.view or {}).get("part"), dict)]
        if present.already_shown(shown, drawn):
            # The rows a tool's result already drew this turn: nothing is shown twice.
            rec.status, rec.output = "ok", {"presented": "already shown"}
            return {"presented": "already shown", "note": SHOWN}
        state.shown += 1
        rec.status, rec.output = "ok", {"presented": said}
        rec.view = {"part": shown, **({"followUps": [*replies]} if replies else {})}
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
    tool.prepare = _offer(state, builtin=True)
    return tool


def _offer(
    state: _TurnState, *, builtin: bool
) -> Callable[[RunContext[None], ToolDefinition], Awaitable[ToolDefinition | None]]:
    async def prepare(ctx: RunContext[None], tool_def: ToolDefinition) -> ToolDefinition | None:
        return tool_def if state.offered(ctx, builtin=builtin) else None

    return prepare


async def _closing_answer(
    model: Any, guard_model: Any, rules: list[Guardrail], system_prompt: str, exchanged: list[ModelMessage]
) -> str:
    """The reply's one request at its budget: an answer in text from what the turn has read, with no tool offered.
    Empty when the request fails, or when a guardrail stops the answer or cannot check it: an unchecked answer is
    never sent."""
    try:
        with finishing():
            closer = Agent[None, str](model, deps_type=type(None), output_type=str, instructions=system_prompt)
            said = await closer.run(
                CLOSING_PROMPT, message_history=exchanged, usage_limits=UsageLimits(request_limit=1)
            )
            text = said.output.strip()
            if text and rules and await guard.check(guard_model, rules, text) is not None:
                return ""
    except Exception:  # the reply then ends with the budget notice alone
        return ""
    return text


def told_before(refused_on: int | None, run_step: int) -> bool:
    """Whether the model had read a refusal made on step `refused_on` before it made a call on `run_step`: only then
    is the call a repeat that ends the turn."""
    return refused_on is not None and run_step > refused_on


class WidgetLimitReached(UsageLimitExceeded):
    """present called after the per-answer widget limit refused it and was withdrawn. Ends the turn with the
    text and widgets it already has."""


class BuiltinLimitReached(UsageLimitExceeded):
    """A kernel tool called again after max_builtin_calls refused it: the turn ends as at the step limit, its partial
    reply marked cut short."""


class ToolLimitExceeded(UsageLimitExceeded):
    """The agent's tool-call budget, raised by the kernel itself. Any other UsageLimitExceeded is the library's
    request limit, which is the agent's step limit: the two end a turn for different reasons and say so differently."""


def _with_skills(system_prompt: str, pinned: list[Skill]) -> str:
    """Always-on skill bodies after the agent's instructions, then the index of on-match skills (spec 11 5.3)."""
    added = skillset.prompt(pinned)
    return f"{system_prompt}\n\n{added}" if added else system_prompt


def _with_earlier(
    system_prompt: str,
    carried: list[Skill],
    reads: list[str],
    plan: Plan | None = None,
    picked: list[Skill] | None = None,
) -> str:
    """The bodies of skills picked for this reply and of skills an earlier turn loaded, the results earlier turns read
    and a plan an earlier turn left open, after the skill index."""
    parts = [f"## {s.name} (picked by the person for this reply)\n\n{s.instructions}" for s in picked or []]
    parts += [f"## {s.name} (loaded earlier in this conversation)\n\n{s.instructions}" for s in carried]
    if plan is not None:
        parts.append(planner.prompt(plan))
    if reads:
        lines = "\n".join(f"- {r}" for r in reads)
        parts.append(f"## {EARLIER_READS}\n\n{lines}")
    return "\n\n".join([system_prompt, *parts]) if parts else system_prompt


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


def _replace(state: _TurnState, text: str, *, guardrail: bool = False) -> TextDelta | TextReplaced:
    """Sends `text` as the answer: a delta when nothing is on screen yet, else a replacement of what streamed. Only a
    guardrail's replacement records what streamed for the audit (TurnResult.retracted): the end check rewording an
    answer takes nothing back from the person."""
    shown = state.shown_text
    state.text = text
    if not shown:
        return TextDelta(text)
    if guardrail and text != shown:
        state.retracted = shown
    state.shown_text = text
    return TextReplaced(text)


def _fired(hit: guard.Hit, when: str) -> GuardrailFired:
    r = hit.rule
    return {"guardrailId": r.guardrail_id, "version": r.version, "name": r.name, "topic": hit.topic, "when": when}


def _plan(state: _TurnState) -> Tool[None]:
    """The built-in plan tool (plan.py), charged to neither the tool cap nor the built-in cap. The model sends the plan
    once; it then ticks itself as each step's reads come back (_tick_plan), so the tool is offered only while the turn
    has no plan, and no model step is ever spent on ticking it."""
    g = state.grants[planner.NAME]

    async def call(ctx: RunContext[None], **arguments: Any) -> Any:
        rec = state.record(ctx.tool_call_id or f"call_{len(state.order)}", planner.NAME, arguments)
        if state.plan is not None:
            rec.status, rec.output = "error", {"error": planner.KEPT}
            return {"error": planner.KEPT}
        new, why = planner.given(arguments)
        if why is None:
            assert new is not None
            why = planner.check(None, new, replan=False, replans=0)
        if why is not None:
            rec.status, rec.output = "error", {"error": why}
            return {"error": why}
        assert new is not None
        state.plan, state.plan_call = new, rec.tool_call_id
        said = planner.answer(new)
        rec.status, rec.output, rec.view = "ok", said, {"part": planner.part(new)}
        return said

    async def prepare(ctx: RunContext[None], tool_def: ToolDefinition) -> ToolDefinition | None:
        return tool_def if state.plan is None and state.free() and state.offered(ctx, builtin=True) else None

    tool = Tool[None].from_schema(
        cast(Callable[..., Awaitable[Any]], call), planner.NAME, g.description, g.input_schema, takes_ctx=True
    )
    tool.prepare = prepare
    return tool


def _tick_plan(state: _TurnState) -> ToolOutput | None:
    """At the start of each model step: when the step that just ended read something, the plan's current step is done
    and the next one starts, with a fresh tool-call budget and max_steps more loop steps, as one ask has."""
    if state.plan is None or planner.finished(state.plan) or state.step not in state.read_steps:
        return None
    if state.plan_call not in state.records:
        return None
    state.plan = planner.ticked(state.plan)
    state.granted_calls, state.cap_told_step = 0, None
    more = state.req.settings.max_steps
    state.step_limit = (state.step_limit or state.req.settings.max_steps) + more
    if state.limits is not None and state.limits.request_limit is not None:
        state.limits.request_limit += more
    rec = state.records[state.plan_call]
    rec.view = {"part": planner.part(state.plan)}
    return ToolOutput(rec)


def _plan_left(state: _TurnState, why: str, *, answered: bool = False) -> ToolOutput | None:
    """A plan the turn stops before finishing, redrawn on its part. Stopped for the person (an approval, a sign-in a
    failed call asked for): its current step is blocked with why. Answered with nothing waiting: the answer finishes
    the step being worked, and steps never started are skipped."""
    if state.plan is None or planner.finished(state.plan) or state.plan_call not in state.records:
        return None
    failed = any(r.status == "error" and r.tool not in KERNEL_TOOLS for r in state.records.values())
    state.plan = planner.closed(state.plan) if answered and not failed else planner.paused(state.plan, why)
    rec = state.records[state.plan_call]
    rec.view = {"part": planner.part(state.plan)}
    return ToolOutput(rec)


def _load_skill(state: _TurnState, grant: ToolGrant) -> Tool[None]:
    """The built-in load_skill tool: returns a pinned on-match skill's body, within the per-turn caps. No port behind
    it and, like present, not charged to the tool-call budget."""

    async def call(ctx: RunContext[None], **arguments: Any) -> Any:
        rec = state.record(ctx.tool_call_id or f"call_{len(state.order)}", skillset.NAME, arguments)
        if (over := state.charge_builtin(ctx.run_step)) is not None:
            rec.status, rec.output = "error", {"error": over}
            return {"error": over}
        slug = str(arguments.get("slug") or "")
        if part := str(arguments.get("part") or ""):
            slug = f"{slug.split('/', maxsplit=1)[0]}/{part}"
        if any(s.slug == slug for s in state.stepped):
            # A skill with steps is never read as text: loading it starts it at step 1, by switch_skill's rules
            # (the one running ends as switched, one already running is refused, a required input is asked for).
            asked: Json = {"slug": slug, "inputs": arguments.get("inputs")}
            moved = step_tools.handle(step_tools.SWITCH, state.run, state.stepped, asked)
            if not moved.ok:
                rec.status, rec.output = "error", {"error": moved.said}
                return {"error": moved.said}
            said = state.moved(moved.run) or moved.said
            rec.status, rec.output = "ok", {"now": said}
            return {"now": said}
        skill, why = skillset.load(state.req.settings.skills, state.loaded, slug, state.carried)
        if skill is None:
            rec.status, rec.output = "error", {"error": why}
            return {"error": why}
        if skill not in state.loaded:
            state.drop_carried()
            state.loaded.append(skill)
            state.loads.append(skillset.loaded_entry(skill, str(arguments.get("matched") or skill.use_when)))
            state.hows.append("loaded")
        rec.status, rec.output = "ok", {"loaded": skill.slug, "version": skill.version}
        return {"skill": skill.name, "version": skill.version, "instructions": skill.instructions}

    async def prepare(ctx: RunContext[None], tool_def: ToolDefinition) -> ToolDefinition | None:
        return tool_def if state.free() and state.offered(ctx, builtin=True) else None

    tool = Tool[None].from_schema(
        cast(Callable[..., Awaitable[Any]], call), skillset.NAME, grant.description, grant.input_schema, takes_ctx=True
    )
    tool.prepare = prepare
    return tool


def _step_tool(state: _TurnState, grant: ToolGrant) -> Tool[None]:
    """One of the step tools (step_tools.py): it moves the running-skill record and tells the model where it now is.
    switch_skill is offered whenever the agent holds a skill with steps; step_done and exit while one runs."""
    cap = step_tools.limit(state.stepped)

    async def call(ctx: RunContext[None], **arguments: Any) -> Any:
        rec = state.record(ctx.tool_call_id or f"call_{len(state.order)}", grant.name, arguments)
        state.step_calls += 1
        if state.step_calls > cap:
            rec.status, rec.output = "error", {"error": f"Stopped: the skill tools were called more than {cap} times."}
            raise BuiltinLimitReached(f"The skill tools were called more than {cap} times in one reply.")
        moved = step_tools.handle(grant.name, state.run, state.stepped, arguments)
        if not moved.ok:
            rec.status, rec.output = "error", {"error": moved.said}
            return {"error": moved.said}
        said = state.moved(moved.run) or moved.said
        # A claim on a step with no tool, or a sub-skill's ending on a step with a sentence check: the judge decides.
        said = await state.judge() or said
        rec.status, rec.output = "ok", {"now": said}
        return {"now": said}

    async def prepare(ctx: RunContext[None], tool_def: ToolDefinition) -> ToolDefinition | None:
        running = grant.name == step_tools.SWITCH or state.run.running is not None
        return tool_def if running and state.offered(ctx, builtin=True) else None

    tool = Tool[None].from_schema(
        cast(Callable[..., Awaitable[Any]], call), grant.name, grant.description, grant.input_schema, takes_ctx=True
    )
    tool.prepare = prepare
    return tool


def _noted(told: Json, note: str | None) -> Json:
    """What the kernel tells the model with a tool result (`note`, `result` or `error`), with what the running skill's
    step made of that result."""
    if note is None:
        return told
    return {**told, "note": f"{told['note']} {note}" if told.get("note") else note}


def _search(state: _TurnState) -> Tool[None]:
    """The built-in search_tools tool over this turn's own offered tools (search.py); no port behind it, and like
    present it is not charged to the tool-call budget."""

    async def call(ctx: RunContext[None], **arguments: Any) -> Any:
        rec = state.record(ctx.tool_call_id or f"call_{len(state.order)}", search.NAME, arguments)
        if (over := state.charge_builtin(ctx.run_step)) is not None:
            rec.status, rec.output = "error", {"error": over}
            return {"error": over}
        # A tool that may not be called now is not named either: its schema would be all the model needs to ask
        # for it.
        offered = [t for t in state.req.tools if state.barred(t.name) is None]
        found = search.search(offered, str(arguments.get("query") or ""))
        rec.status, rec.output = "ok", {"tools": found}
        return {"tools": found}

    async def prepare(ctx: RunContext[None], tool_def: ToolDefinition) -> ToolDefinition | None:
        return tool_def if state.free() and state.offered(ctx, builtin=True) else None

    tool = Tool[None].from_schema(
        cast(Callable[..., Awaitable[Any]], call),
        search.NAME,
        search.SEARCH.description,
        search.SEARCH.input_schema,
        takes_ctx=True,
    )
    tool.prepare = prepare
    return tool


def _tool(state: _TurnState, ports: KernelPorts, grant: ToolGrant, *, deferred: bool = False) -> Tool[None]:
    resume = state.req.resume
    token = resume.approval_token if resume and resume.decision == "approved" else None

    async def call(ctx: RunContext[None], **arguments: Any) -> Any:
        tool_call_id = ctx.tool_call_id or f"call_{len(state.order)}"
        if grant.name == SEARCH_KNOWLEDGE:
            own = _own_knowledge(state.req, arguments)
            if own is None:
                rec = state.record(tool_call_id, grant.name, arguments)
                rec.status, rec.output = "error", {"error": NO_OWN_KNOWLEDGE}
                return {"error": NO_OWN_KNOWLEDGE}
            arguments = own
        # Asked again here, and before a person is asked to approve: the offer was made before this model step's
        # other calls ran, and one of them may have started or left a skill.
        if (why := state.barred(grant.name)) is not None:
            rec = state.record(tool_call_id, grant.name, arguments)
            rec.status, rec.output = "error", {"error": why}
            return {"error": why}
        if grant.gated and not ctx.tool_call_approved:
            # A write stops at a gate: the library ends the run with a deferred request (spec 15 5).
            raise ApprovalRequired()
        # Where the running skill stood when this call started, when it is that step's tool: its result is checked
        # for that step only, so a result that arrives after the step moved changes nothing.
        at = state.position() if steps.target(state.run) == grant.name else None
        asked = input_hash(arguments)
        if (running := state.inflight.get((grant.name, asked))) is not None:
            # The same call twice in one step: the library runs a step's calls together, so the first is still out.
            await running.wait()
        same = next(
            (r for r in state.records.values() if r.tool == grant.name and r.input_hash == asked and r.status in DONE),
            None,
        )
        if same is not None:
            # The same call again in one reply is not sent to the system twice, and from here the model is offered no
            # system tool, so it answers from what it has: a summary turn repeated one read until the tool cap ended
            # it with no answer.
            state.tools_closed = True
            rec = state.record(tool_call_id, grant.name, arguments)
            # Its card names the call it repeats, which already shows the result, so nothing is drawn twice.
            rec.status, rec.output = same.status, {"repeatOf": same.tool_call_id}
            note = await state.step_result(ctx.run_step, at, same.output, same.status == "ok")
            return _noted({"note": REPEATED_CALL, "result": same.output}, note)
        # A read this conversation already made answers from what it kept (tool_cache.py): it reaches no system and
        # spends none of the tool budget.
        cache = await ports.tool_caches.current() if ports.tool_caches is not None else None
        if cache is not None and grant.access == "read" and (kept := cache.get(grant.server, grant.name, asked)):
            rec = state.record(tool_call_id, grant.name, arguments)
            rec.status, rec.output, rec.cached = "ok", kept.output, True
            state.read_steps.add(state.step)
            said = kept.for_model if kept.for_model is not None else _numbered(state, kept.output)
            note = await state.step_result(ctx.run_step, at, kept.output, True)
            return _noted({"note": tool_cache.EARLIER, "result": said}, note)
        # The agent's tool-call budget counts the calls that reach a system; the built-in present tool reaches none
        # and is bounded by the step limit instead, so an agent with no tool calls can still answer with a widget.
        cap = state.req.settings.max_tool_calls
        if cap is not None and state.granted_calls >= cap:
            # Past the budget with reads already made, every call of that step is told to stop, so the reply answers
            # from what was read; a call after that step, or a budget hit before any read, ends the turn.
            told = state.cap_told_step
            if state.granted_calls > 0 and (told is None or told == ctx.run_step):
                state.cap_told_step = ctx.run_step
                rec = state.record(tool_call_id, grant.name, arguments)
                rec.status, rec.output = "error", {"error": NOT_RUN["max_tool_calls"]}
                return {"error": TOOL_BUDGET_SPENT.format(cap=cap)}
            raise ToolLimitExceeded(f"The agent may make {cap} tool calls a reply.")
        state.granted_calls += 1
        rec = state.record(tool_call_id, grant.name, arguments)
        done = state.inflight[(grant.name, asked)] = asyncio.Event()
        try:
            started = time.monotonic()
            # A call a person approved carries the token: a gated write's, or one the gateway sent for review.
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
            if outcome.ok:
                state.read_steps.add(state.step)
                if cache is not None and grant.access == "read":
                    cache.put(grant.server, grant.name, asked, outcome.output, outcome.for_model)
                elif cache is not None:
                    # A write or a workflow may have changed what was read from this app.
                    cache.wrote(grant.server)
            rec.output = outcome.output
            rec.view = outcome.view
            rec.signed_in = outcome.signed_in
            part = (outcome.view or {}).get("part")
            drawn = [
                p for r in state.records.values() if r is not rec and isinstance(p := (r.view or {}).get("part"), dict)
            ]
            if part and present.already_shown(part, drawn):
                # A record or rows an earlier call this turn already drew (a query's row, then the same record read by
                # id): drawn once.
                rec.view = None
            said = outcome.for_model if outcome.for_model is not None else outcome.output
            if outcome.ok and outcome.for_model is None:
                before = len(state.passages)
                said = _numbered(state, outcome.output)
                if len(state.passages) > before:
                    state.passage_calls.add(rec.tool_call_id)
            # A rule check reads the result as the system returned it, before anything is masked.
            note = await state.step_result(ctx.run_step, at, outcome.output, outcome.ok)
            if outcome.ok and (outcome.view or {}).get("part"):
                # Drawn for the person already (a table or a record): told so, the model answers in text instead of
                # presenting the same rows a second time.
                return _noted({"note": SHOWN, "result": said}, note)
            # Errors go back to the model as information so it can explain or try other arguments (spec 15 4.2).
            if note is not None:
                return _noted({"result": said} if outcome.ok else {"error": said}, note)
            return said if outcome.ok else {"error": said}
        finally:
            done.set()
            state.inflight.pop((grant.name, asked), None)

    tool = Tool[None].from_schema(
        cast(Callable[..., Awaitable[Any]], call),
        grant.name,
        grant.description,
        grant.input_schema,
        takes_ctx=True,
        # Reads may run side by side; anything that can change a system (a write, a workflow, another agent) runs
        # one at a time, in the order the model asked.
        sequential=grant.access != "read" or grant_token(grant.name) is not None,
    )
    # Above the agent's tool-search threshold its schema is sent only once a search finds it.
    tool.defer_loading = deferred

    async def prepare(ctx: RunContext[None], tool_def: ToolDefinition) -> ToolDefinition | None:
        if not state.offered(ctx, builtin=False) or state.barred(grant.name) is not None:
            return None
        if deferred and grant.name == steps.target(state.run):
            # Sent with its schema even when the agent searches for its tools: the step cannot pass without it.
            return replace(tool_def, defer_loading=False)
        return tool_def

    tool.prepare = prepare
    return tool


def _numbered(state: _TurnState, output: JsonValue) -> Any:
    """A result's passages (`{"passages": [{text, title, section?, page?, knowledgeBase?, itemId?}]}`) numbered on from
    the turn's, so the model cites them as it cites the knowledge block; any other result as it is."""
    if not isinstance(output, dict):
        return output
    result = output
    answers = result.get("answers")
    if isinstance(answers, dict):
        for kb, a in answers.items():
            if isinstance(a, dict) and kb not in state.kb_answers:
                state.kb_answers[str(kb)] = BaseAnswer.of(a)
    found = result.get("passages")
    if not isinstance(found, list) or not found:
        return result
    numbered: JsonList = []
    for raw in found:
        if not isinstance(raw, dict) or not raw.get("text"):
            numbered.append(raw)
            continue
        p = raw
        state.passages.append(
            Passage(
                document_id=str(p.get("itemId") or p.get("documentId") or ""),
                title=str(p.get("title") or ""),
                section=str(p.get("section") or ""),
                version=str(p.get("version") or ""),
                text=str(p["text"]),
                kb_id=str(p.get("knowledgeBase") or ""),
                page=page if isinstance(page := p.get("page"), int) else None,
            )
        )
        numbered.append({"n": len(state.passages), **p})
    return {**result, "passages": numbered}


async def _retrieve(req: TurnRequest, ports: KernelPorts, state: _TurnState) -> list[Passage]:
    """The knowledge block: the bases' own retrieval settings decide how many passages return (kb-service), and
    their answer settings are kept for the end of the turn."""
    query = (req.search_text or req.user_turn or "").strip()
    if not req.kb_ids or not query:
        return []
    found = await ports.knowledge.search(query, req.kb_ids)
    state.kb_answers.update(getattr(found, "answers", None) or {})
    return list(found)


def _own_knowledge(req: TurnRequest, arguments: Json) -> Json | None:
    """A search_knowledge call as the turn may make it. The tool searches only the bases named, or every base of the
    team when the call says `allTeamKnowledgeBases`, which the kernel alone sets, for an agent given that option; a
    model's own flag is dropped. Otherwise the call is narrowed to the turn's own bases, as grounding is: those the
    model named among them, else all of them. None when the turn has none."""
    asked = {k: v for k, v in arguments.items() if k != ALL_TEAM}
    if req.all_team_knowledge:
        return {**asked, ALL_TEAM: True} if not asked.get("collections") else asked
    if not req.kb_ids:
        return None
    named = [str(c) for c in cast(list[Any], asked.get("collections") or [])]
    kept = [c for c in named if c in req.kb_ids]
    collections: JsonList = [*(kept or req.kb_ids)]
    return {**asked, "collections": collections}


def _kept_run(kept: SkillRunState, stepped: list[Skill], has: list[Skill], *, new_reply: bool) -> SkillRunState:
    """The record a turn goes on with. A running skill finishes on the steps of the version it started, which the
    record holds; while the agent still pins that version, its own steps and notes are used, because the record a
    reply returned may hold them masked. A new reply (not one going on after a pause) starts with no ending marked
    as its own."""
    run = kept.model_copy(deep=True)
    if new_reply:
        for ended in run.history:
            ended.in_reply = False
        steps.trim(run)
    running = run.running
    for frame in (running, running.sub if running is not None else None):
        if frame is None:
            continue
        at = (frame.skill_id, frame.version)
        pinned = next((s for s in stepped if (s.skill_id, s.version) == at and s.program is not None), None)
        if pinned is not None and pinned.program is not None:
            frame.program, frame.rules = pinned.program, pinned.instructions
    # Only the holder ends a hold, by passing the step it was taken on. A skill the agent no longer has, or has in
    # another version, cannot do that, so what it held is free: the model is never pointed at a skill it cannot
    # start, or at a step that may no longer exist.
    # `has` is every skill with steps the agent has, whether or not this turn can run them.
    pins = {(s.skill_id, s.version) for s in has}
    run.holds = [h for h in run.holds if (h.skill_id, h.version) in pins]
    return run


def _names(req: TurnRequest) -> dict[str, str]:
    """What the model knows each reference in a step's text as: a skill by its slug, an agent or a workflow by the
    name of the tool that calls it. A tool is known by its id, as written."""
    names = {f"@skill:{s.skill_id}": s.slug for s in req.settings.skills}
    names.update({token: t.name for t in req.tools if (token := grant_token(t.name)) is not None})
    return names


def _model_settings(req: TurnRequest) -> ModelSettings | None:
    """The settings sent with each model request; None when the agent sets none, so the model's defaults hold.

    One order: the agent version's saved knobs, then a caller's temperature within the agent's limits over the saved
    one. The older `thinking` pattern applies only when the version saved neither a thinking budget nor an effort.
    A knob name this does not map is not sent."""
    sent = ModelSettings()
    saved = req.settings.model_settings
    body: dict[str, Any] = {}
    # temperature, top_p and max_tokens go as the OpenAI client's own settings; the others in the request body under
    # the names models-service reads (`thinking` in Anthropic's form for a budget).
    for name, value in saved.items():
        if name == "temperature" and not isinstance(value, str):
            sent["temperature"] = float(value)
        elif name == "top_p" and not isinstance(value, str):
            sent["top_p"] = float(value)
        elif name == "max_tokens" and isinstance(value, int):
            sent["max_tokens"] = value
        elif name == "reasoning_effort":
            body["reasoning_effort"] = value
        elif name == "top_k":
            body["top_k"] = value
        elif name == "thinking_budget" and isinstance(value, int) and value > 0:
            body["thinking"] = {"type": "enabled", "budget_tokens": value}
    if req.settings.temperature is not None:
        sent["temperature"] = req.settings.temperature
    if req.settings.thinking in ("low", "medium", "high") and not {"thinking_budget", "reasoning_effort"} & set(saved):
        sent["thinking"] = req.settings.thinking
    if not req.settings.parallel_reads:
        sent["parallel_tool_calls"] = False
    if body:
        sent["extra_body"] = body
    return sent or None


def _close_open(state: _TurnState, why: str) -> list[ToolOutput]:
    """Every call the turn left running, closed as not run: a card shows each call's end, never "Running" after the
    reply is over."""
    closed: list[ToolOutput] = []
    for rec in state.records.values():
        if rec.status == "running":
            rec.status, rec.output = "error", {"error": why}
            closed.append(ToolOutput(rec))
    return closed


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
        plan=state.plan,
        run=state.run.model_copy(deep=True) if state.tracks else None,
        held={k: list(v) for k, v in state.held.items()},
    )


GUARDRAIL_UNAVAILABLE = (
    "I could not check this question against this agent's guardrails just now, so I have not answered it. Try again "
    "shortly."
)
# What a call that finished this reply ended as; a repeat of one is answered from it.
DONE = ("ok", "error")
REPEATED_CALL = (
    "You already made this call with these arguments in this reply, and this is its result. Answer from what you have."
)
# Each tool call still open when a limit or the deadline ends the turn is closed as not run, with why.
NOT_RUN = {
    "max_tool_calls": "Not run: the reply reached the most tool calls this agent may make.",
    "max_steps": "Not run: the reply reached its step limit.",
    "budget_reached": "Not run: the conversation reached its budget.",
    "deadline": "Not run: the reply took too long and was stopped.",
}
TOOL_LIMIT_REACHED = (
    "I reached the most tool calls this agent may make in one reply before I could answer. Ask again, or narrow the "
    "question."
)
# What a kernel tool answers past the agent's max_builtin_calls; said as an instruction, as present's widget cap is.
BUILTIN_LIMIT = (
    "This turn has used its {cap} calls to present, search_tools and load_skill. Do not call them again; answer in "
    "text now from what you have."
)
# What a call past max_tool_calls answers when the reply already read something, so it answers from that.
TOOL_BUDGET_SPENT = (
    "Not run: this reply has used its {cap} tool calls. Do not call another tool; answer now from the results you "
    "already have, and say in one line what you could not read."
)
# What a skill carried from an earlier turn was loaded for, and the heading of the reads earlier turns made.
EARLIER = "earlier in this conversation"
EARLIER_READS = (
    "Read earlier in this conversation. Answer from these; read again only for what they do not hold, or when the "
    "person asks for fresh data"
)
STEP_LIMIT_REACHED = "I reached the step limit for one reply before I could answer. Ask again, or narrow the question."
# Appended when a limit stops a turn that had already written part of its answer, so a partial reply never reads as
# a complete one.
CUT_SHORT_TOOLS = "\n\n(Reply cut short: the agent reached the most tool calls it may make in one reply.)"
CUT_SHORT_STEPS = "\n\n(Reply cut short: the agent reached its step limit for one reply.)"
BUDGET_REACHED = "This conversation reached its budget before I could answer."
CUT_SHORT_BUDGET = "\n\n(Reply cut short: the conversation reached its budget.)"
# The one request a reply may still make at its budget, with no tool offered (ports.BudgetReachedError.closing).
CLOSING_PROMPT = (
    "The budget for this conversation is spent, so you can make no more tool calls. Answer now, in text, from what "
    "you already have, and say plainly what you could not finish."
)
KNOWLEDGE_UNAVAILABLE = (
    "The knowledge service is not available right now, so I cannot answer from the knowledge bases. Try again shortly."
)
KNOWLEDGE_WITHDRAWN = (
    "The knowledge this conversation searches is no longer available to this agent, so I cannot answer from it. "
    "Start a new conversation, or ask the agent's owner to grant the knowledge base again."
)


def _system_calls(state: _TurnState) -> list[ToolCallRecord]:
    """Calls that reached a system; the kernel's own tools say nothing about whether the person's ask was answerable."""
    return [r for i in state.order if (r := state.records[i]).server != UNGRANTED and r.tool not in KERNEL_TOOLS]


def _base_withholds(state: _TurnState, block: int, asked: bool) -> str | None:
    """The no-answer message that replaces the answer, or None. An answer has a source when it cites a passage, when
    a call to a system brought a result this turn, or when the person attached a file whose text the turn holds;
    only an answer with none of these is withheld. Then, when it comes from knowledge (the block, calls that each
    brought passages, or knowledge asked for and nothing found), the first searched base (kb_ids order) whose answer
    settings withhold an uncited answer has its message said instead. Runs after the end check, so a correction that
    adds citations keeps the answer, and whether or not the agent turns the end check on."""
    rule = next((a for a in state.kb_answers.values() if a.withholds and a.no_answer_message), None)
    if rule is None or cited_numbers(state.text) or state.req.attached:
        return None
    systems = _system_calls(state)
    from_knowledge = all(r.tool_call_id in state.passage_calls for r in systems) if systems else block > 0 or asked
    return rule.no_answer_message if from_knowledge else None


async def _end_check(
    state: _TurnState, model: Any, system_prompt: str, history: list[ModelMessage], block: int
) -> tuple[str | None, TokenUsage]:
    """The end-clean check (answer_check.py) on the finished answer: None when it is clean, else the one correction,
    made by a tool-less agent told each defect. A correction that fails, comes back empty or has more defects than the
    answer leaves the answer as it was; there is never a second one."""
    systems = _system_calls(state)
    # A question the model gave its likely answers for (present followUps) is the interview's own, not an offer.
    interviewed = any(
        r.tool == present.NAME and r.status == "ok" and (r.view or {}).get("followUps") for r in state.records.values()
    )
    reads_ok = not interviewed and bool(systems) and all(r.status == "ok" and r.access == "read" for r in systems)
    offered = frozenset(state.grants)
    read_only = not interviewed and all(r.access == "read" for r in systems)
    # From knowledge only: the block with no call, or calls that each brought passages (search_knowledge).
    from_knowledge = (block > 0 and not systems) or (
        bool(systems) and all(r.tool_call_id in state.passage_calls for r in systems)
    )
    found = answer_check.defects(
        state.text,
        needs_citation=from_knowledge,
        all_reads_succeeded=reads_ok,
        tools=offered,
        read_only=read_only,
    )
    if not found:
        return None, TokenUsage()
    try:
        fixer = Agent[None, str](model, deps_type=type(None), output_type=str, instructions=system_prompt)
        with finishing():
            again = await fixer.run(
                answer_check.correction_prompt(found),
                message_history=history,
                usage_limits=UsageLimits(request_limit=1),
            )
    except Exception:  # a correction that fails leaves the answer as written
        return None, TokenUsage()
    u = again.usage
    spent = TokenUsage(u.input_tokens, u.output_tokens, u.requests)
    corrected = again.output.strip()
    if not corrected:
        return None, spent
    still = answer_check.defects(
        corrected,
        needs_citation=from_knowledge,
        all_reads_succeeded=reads_ok,
        tools=offered,
        read_only=read_only,
    )
    # Citing adds numbers to what was said; a citation fix that drops most of the answer (a full reply rewritten as
    # "I could not find it") is worse than the missing number, so the answer stays as written.
    kept = not from_knowledge or len(corrected) >= len(state.text.strip()) // 2
    return (corrected if kept and len(still) < len(found) else None), spent


async def run_turn(req: TurnRequest, ports: KernelPorts) -> AsyncIterator[KernelEvent]:
    """Streams one turn's events, ending with exactly one `TurnFinished`. With the agent's redactPii on, what
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
        elif isinstance(event, SkillRunChanged):
            yield SkillRunChanged(pii.masked_run(event.run))
        elif isinstance(event, TurnFinished):
            yield TurnFinished(pii.masked_result(event.result))
        else:
            yield event


async def _turn(req: TurnRequest, ports: KernelPorts) -> AsyncIterator[KernelEvent]:
    """One turn's events as the model's loop produces them."""
    # Every turn may present a shaped answer (a comparison table) without a tool behind it. A structured
    # call with no tools (memory extraction, a workflow's AI step) answers with its schema's JSON only, so it is offered
    # nothing to call.
    builtins = bool(req.tools) or req.output_schema is None
    # Many tools: each is deferred and pydantic-ai's tool search (search.strategy) reveals the ones the model finds;
    # its `search_tools` replaces the kernel's own, so that one is not added.
    above = req.settings.tool_search_above
    searching = builtins and above is not None and len(req.tools) > above
    state = _TurnState(
        req=req,
        grants={
            **{t.name: t for t in req.tools},
            **(
                {present.NAME: present.grant(req.settings), search.NAME: search.SEARCH, planner.NAME: planner.GRANT}
                if builtins
                else {}
            ),
        },
    )
    tools = [_tool(state, ports, g, deferred=searching) for g in sorted(req.tools, key=lambda t: t.name)] + (
        [_present(state), _plan(state), *([] if searching else [_search(state)])] if builtins else []
    )
    # Skills that run step by step are driven by their own tools, and the record of the one running is read before
    # anything can end the turn, so every way out returns it.
    state.stepped = step_tools.stepped(req.settings.skills) if builtins else []
    state.owned = steps.owned(state.stepped, {t.name: t.access for t in req.tools})
    for step_grant in step_tools.grants(state.stepped):
        state.grants[step_grant.name] = step_grant
        tools.append(_step_tool(state, step_grant))
    kept_run = req.resume.interrupt.run if req.resume else req.carried_run
    state.tracks = bool(state.stepped) or kept_run is not None
    if kept_run is not None:
        state.run = _kept_run(
            kept_run, state.stepped, step_tools.stepped(req.settings.skills), new_reply=req.resume is None
        )
        if req.settings.redact_pii and not req.resume:
            state.run = pii.remarked(state.run)
    if req.resume:
        state.held = {k: list(v) for k, v in req.resume.interrupt.held.items()}
    # A plan the turn goes on with: kept at its pause (an approval), or left open by an earlier turn (a Connect card).
    carried_plan = req.carried_plan if planner.stored(req.carried_plan) else None
    state.plan = (req.resume.interrupt.plan if req.resume else None) or carried_plan
    # A skill an earlier turn loaded is carried in whole (below): it is neither listed to load nor loadable again.
    loadable = [s for s in req.settings.skills if not any(skillset.same(s, e) for e in req.carried_skills)]
    if (load_grant := skillset.grant(loadable, state.stepped)) is not None:
        state.grants[skillset.NAME] = load_grant
        tools.append(_load_skill(state, load_grant))
    for s in req.settings.skills:
        if s.loading == "always" and s.program is None:
            state.loaded.append(s)
            state.loads.append(skillset.loaded_entry(s, skillset.ALWAYS))
            state.hows.append("always")
    # A resumed turn keeps the on-match skills it loaded before the pause (already journalled, so not loaded again).
    for entry in req.resume.interrupt.loaded_skills if req.resume else []:
        skill = next(
            (s for s in req.settings.skills if skillset.same(s, entry) and s.version == entry["version"]), None
        )
        if skill is not None and skill.program is None and skill not in state.loaded:
            state.loaded.append(skill)
            state.loads.append(entry)
            state.hows.append(str(entry.get("how") or "loaded"))
            state.restored += 1
    # Skills an earlier turn loaded stay loaded (pinned at their current version), outside this turn's load caps. A
    # part the person picked for this reply arrives the same way but counts against the caps (it is not carried).
    carried: list[Skill] = []
    picked: list[Skill] = []
    for entry in req.carried_skills:
        skill = next((s for s in req.settings.skills if skillset.same(s, entry)), None)
        if skill is not None and skill.program is not None:
            # A skill with steps is never carried as text. Picked from the menu for this reply, it starts (and the
            # one running ends as switched), unless it is the one already running.
            running = state.run.running
            menu = entry.get("how") == "picked" and skill in state.stepped and not req.resume
            if menu and (running is None or running.skill_id != skill.skill_id):
                inputs = {k: str(v) for k, v in json_object(entry.get("inputs")).items()}
                if missing := steps.missing_inputs(skill, inputs):
                    state.unstarted = step_tools.needs(skill, missing)
                else:
                    told: list[str] = []
                    halted = state.moved(
                        steps.start(state.run, skill, state.stepped, by="menu", inputs=inputs, told=told)
                    )
                    state.unstarted = halted or " ".join(told)
            continue
        if skill is not None and skill.loading == "on_match" and skill not in state.loaded:
            how = "picked" if entry.get("how") == "picked" else "carried"
            state.loaded.append(skill)
            inputs = {k: str(v) for k, v in json_object(entry.get("inputs")).items()}
            state.loads.append(skillset.loaded_entry(skill, str(entry.get("matched") or EARLIER), inputs))
            state.hows.append(how)
            (picked if how == "picked" else carried).append(skill)
            state.restored += 1
    state.carried = carried
    # A person rejected the call the turn paused on. The library answers the model for it and the tool never runs,
    # so the skill whose step called it ends here, as failed.
    rejected = req.resume.interrupt.pending_call.tool if req.resume and req.resume.decision == "rejected" else None
    if rejected is not None and steps.target(state.run) == rejected:
        state.moved(steps.denied(state.run, state.stepped))
    passages: list[Passage] = []
    digest: dict[str, str] = {}
    all_messages: list[ModelMessage] = []
    usage = TokenUsage()

    # Filled once the turn's rules are known; a turn that ends before then checked none.
    checked: list[Guardrail] = []

    def ref(g: Guardrail) -> GuardrailRef:
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
        every = state.passages
        cited = [CitationRef(n, every[n - 1]) for n in cited_numbers(state.text) if 0 < n <= len(every)]
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
                usage=TokenUsage(
                    usage.input_tokens + state.judge_spent.input_tokens,
                    usage.output_tokens + state.judge_spent.output_tokens,
                    usage.requests + state.judge_spent.requests,
                ),
                skills=list(state.loads),
                withheld=state.withheld or None,
                retracted=state.retracted or None,
                guardrails_checked=[ref(g) for g in dict.fromkeys(checked)],
                guardrails_off=[ref(g) for g in req.settings.guardrails_off],
                run=state.run.model_copy(deep=True) if state.tracks else None,
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
    # So are the guardrails of a skill with steps that is running as the turn starts.
    if (on := state.run.running) is not None:
        ids = {on.skill_id, on.sub.skill_id if on.sub is not None else on.skill_id}
        rules.extend(g for s in state.stepped if s.skill_id in ids for g in skillset.guardrails_of(s))
    guarded = bool(rules) or any(s.guardrails for s in req.settings.skills)
    # A guarded answer streams as it is written and is replaced if its after-answer check fails, unless a rule known at
    # the start holds it until checked. A skill loaded mid-turn cannot hold: its guardrails never do (skills.py).
    streaming = not guarded or not any(r.hold for r in rules)
    checked.extend(rules)
    model = ports.models.model_for(req.settings.model_alias) if ports.models is not None else ports.model
    guard_model = guard.model_for(ports.models, model)
    state.judge_model = judge.model_for(ports.models, model)
    if rules and req.user_turn and not req.resume:
        # A question about a blocked topic gets the guardrail's message; the answering model is never called.
        try:
            hit = await guard.check(guard_model, rules, req.user_turn)
        except BudgetReachedError:
            # Nothing is written yet, so there is nothing to close on.
            state.text = BUDGET_REACHED
            yield TextDelta(BUDGET_REACHED)
            yield finish("completed", "budget_reached")
            return
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
    if not req.resume:
        for entry, how in zip(state.loads, state.hows, strict=True):
            yield skillset.event(entry, how)
    for raised in state.events:
        yield raised
    state.events.clear()
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
            # Attached files' pages come first: they are what the person asked about, numbered before knowledge.
            passages = list(req.attached)
            state.passages = list(passages)
            if req.kb_ids and req.user_turn:
                yield StatusChanged("retrieving")
                try:
                    passages = [*req.attached, *await _retrieve(req, ports, state)]
                    state.passages = list(passages)
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
                attachments=req.attachments,
            )
            digest = ctx.digest
            history, results, system_prompt, user_prompt = ctx.history, None, ctx.system_prompt, ctx.user_prompt
    except UnknownVariableError as e:
        yield finish("failed", "error", error=str(e))
        return

    names = _names(req)

    def instructions(_: RunContext[None] | None = None) -> str:
        """The system prompt, written again before every model request: the skill lists and what earlier replies
        left, then what must come last and can change inside a turn: the running skill's current step, its rules,
        and the never rules."""
        written = _with_earlier(
            _with_skills(system_prompt, loadable), state.carried, req.earlier_reads, carried_plan, picked
        )
        if state.unstarted and state.run.running is None:
            written = f"{written}\n\n# A skill the person picked did not start\n{state.unstarted}"
        last = prompt_writer.tail(steps.now(state.run, names), req.settings.never, req.settings.never_heading)
        return f"{written}\n\n{last}" if last else written

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
    finder = ToolSearch[None](strategy=search.strategy, max_results=search.LIMIT, tool_description=search.DEFERRED)
    agent = Agent[None, Any](
        model,
        deps_type=type(None),
        output_type=[answer_type, DeferredToolRequests],
        tools=tools,
        instructions=instructions,
        capabilities=[finder] if searching else None,
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
    state.limits = limits
    if state.plan is not None and state.plan_call is None:
        # A plan this turn goes on with: drawn at once, and ticked like one made here.
        rec = state.record(f"plan_{req.turn_id}", planner.NAME, {"title": state.plan["title"]})
        rec.status, rec.output, rec.view = "ok", planner.answer(state.plan), {"part": planner.part(state.plan)}
        state.plan_call = rec.tool_call_id
        yield ToolOutput(rec)
    writing = False
    output: Any = None
    # The run's event handle, kept for the messages exchanged so far when the run ends early at the budget.
    events: Any = None
    try:
        async with asyncio.timeout(req.deadline_seconds):
            async with agent.run_stream_events(
                user_prompt,
                message_history=history,
                deferred_tool_results=results,
                usage_limits=limits,
                model_settings=_model_settings(req),
            ) as stream:
                events = stream
                async for event in stream:
                    if isinstance(event, PartStartEvent):
                        if event.index == 0:
                            if (ticked := _tick_plan(state)) is not None:
                                yield ticked
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
                        elif rec.status == "running":
                            # A call no kernel function recorded (pydantic-ai's search_tools): its result as returned.
                            rec.status, rec.output = "ok", event.part.content
                        yield ToolOutput(rec)
                        for raised in state.events:
                            yield raised
                        state.events.clear()
                    elif isinstance(event, AgentRunResultEvent):
                        output = event.result.output
                        all_messages = event.result.all_messages()
                        u = event.result.usage
                        usage = TokenUsage(u.input_tokens, u.output_tokens, u.requests)
    except TimeoutError:
        if (cleared := _withhold(state, guarded)) is not None:
            yield cleared
        for closed in _close_open(state, NOT_RUN["deadline"]):
            yield closed
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
    except BudgetReachedError as e:
        if (cleared := _withhold(state, guarded)) is not None:
            yield cleared
        for closed in _close_open(state, NOT_RUN["budget_reached"]):
            yield closed
        closing = ""
        if e.closing and req.output_schema is None:
            exchanged: list[ModelMessage] = events.all_messages() if events is not None else history
            closing = await _closing_answer(model, guard_model, rules, instructions(), exchanged)
        said = closing if closing else (CUT_SHORT_BUDGET if state.text else BUDGET_REACHED)
        if closing and state.text:
            said = f"\n\n{closing}"
        state.text += said
        yield TextDelta(said)
        yield finish("completed", "budget_reached", error=None)
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
        stop = "max_tool_calls" if tools else "max_steps"
        for closed in _close_open(state, NOT_RUN[stop]):
            yield closed
        yield finish("completed", stop, error=None)
        return
    except UnexpectedModelBehavior as e:
        if (cleared := _withhold(state, guarded)) is not None:
            yield cleared
        if req.output_schema is None and state.last_step(state.step):
            # A model that calls a tool on the last step, where none is offered, ends the turn at the step limit.
            notice = CUT_SHORT_STEPS if state.text else STEP_LIMIT_REACHED
            state.text += notice
            yield TextDelta(notice)
            for closed in _close_open(state, NOT_RUN["max_steps"]):
                yield closed
            yield finish("completed", "max_steps", error=None)
            return
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
            error=refusal_text(e.status_code, e.body),
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
        if (held := _plan_left(state, "waiting for your approval")) is not None:
            yield held
        interrupt = _interrupt(state, output, all_messages)
        rec = state.records[interrupt.pending_call.tool_call_id]
        yield ToolOutput(rec)
        yield Interrupted(interrupt)
        yield finish("interrupted", "interrupt", interrupt=interrupt)
        return

    if (held := _plan_left(state, "waiting for you", answered=bool(state.text.strip()))) is not None:
        # The turn ends with steps left (a Connect card, a question): the next turn goes on from this step.
        yield held
    if req.settings.end_check and req.output_schema is None and state.text.strip():
        # Checked before any guardrail, so a corrected answer is the one the guardrail checks.
        corrected, spent = await _end_check(state, model, instructions(), all_messages, len(passages))
        usage = TokenUsage(
            usage.input_tokens + spent.input_tokens,
            usage.output_tokens + spent.output_tokens,
            usage.requests + spent.requests,
        )
        if corrected is not None:
            if state.shown_text:
                yield _replace(state, corrected)
            else:
                state.text = corrected
    asked = req.knowledge_asked if req.knowledge_asked is not None else bool(req.kb_ids)
    withheld_by_base = False
    if req.output_schema is None and state.text.strip():
        message = _base_withholds(state, len(passages) - len(req.attached), bool(asked and req.user_turn))
        if message is not None:
            withheld_by_base = True
            if state.shown_text:
                yield _replace(state, message)
            else:
                state.text = message

    fired: GuardrailFired | None = None
    noted: GuardrailFired | None = None
    # Skills loaded during the reply add their guardrails to the check of the answer.
    always_count = sum(1 for s in req.settings.skills if s.loading == "always" and s.program is None)
    for s in [*state.loaded[always_count:], *state.started]:
        rules.extend(skillset.guardrails_of(s))
        # The answer is checked against them, so the turn records them as checked.
        checked.extend(skillset.guardrails_of(s))
    for entry, how in list(zip(state.loads, state.hows, strict=True))[always_count + state.restored :]:
        yield skillset.event(entry, how)
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
                with finishing():
                    hit = await guard.check(guard_model, rules, state.text)
            except guard.GuardrailUnavailable as e:
                yield _replace(state, GUARDRAIL_UNAVAILABLE, guardrail=True)
                yield finish("failed", "guardrail_unavailable", error=str(e), error_code="guardrail_unavailable")
                return
            if hit is not None:
                if not state.shown_text:
                    state.withheld = state.text
                corrected = ""
                try:
                    fixer = Agent[None, str](model, deps_type=type(None), output_type=str, instructions=instructions())
                    with finishing():
                        again = await fixer.run(
                            f"Your answer touched a blocked topic ({hit.topic}). Answer the question again without "
                            "it, using only what you already found.",
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
                        with finishing():
                            still = await guard.check(guard_model, rules, corrected)
                    except guard.GuardrailUnavailable as e:
                        yield _replace(state, GUARDRAIL_UNAVAILABLE, guardrail=True)
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
            yield _replace(state, state.text, guardrail=True)
        if fired is not None:
            yield finish("completed", "guardrail", guardrail=fired)
            return

    structured = {"output": output} if req.output_schema is not None else {}
    done = finish(
        "completed",
        "final",
        no_answer=withheld_by_base or bool(asked and req.user_turn and not passages and not state.order),
        **structured,
        **({"guardrail": noted} if noted is not None else {}),
    )
    if done.result.citations:
        yield CitationsReady(done.result.citations)
    yield done
