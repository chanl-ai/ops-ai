"""Console chat on the graph path: a chat thread is a thread on the agent wrapper graph, a message is a run, and the
messages the console shows are rebuilt from the runs' inputs and the thread event log.

One translator, `AssistantBuilder`, turns events into the console's `ChatStreamEvent`s and the assistant message they
add up to. The send route feeds it the run's events live; reading a thread feeds it the stored ones; so what streamed
and what is shown on reload come from the same code.

Message ids are derived, never stored: a user message keeps the id the send route put in the run input, and the
assistant message of a run is `m_<run id>`. Feedback and superseded turns are thread events, latest wins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, cast

from pydantic import TypeAdapter

from ops_access import can
from ops_agent_kernel.plan import NAME as PLAN_TOOL
from ops_agent_kernel.search import NAME as SEARCH_TOOL
from ops_agents.activities.catalog import Catalog
from ops_agents.activities.tools import fill
from ops_contracts.chat import (
    AgentAskedEvent,
    ApprovalState,
    ApprovalWidget,
    BudgetPause,
    ChatMessage,
    ChatStreamEvent,
    ChatThread,
    ChatThreadRow,
    Citation,
    CitationsEvent,
    EffectiveSettings,
    GuardrailAudit,
    GuardrailHit,
    LabelValue,
    LoadedSkill,
    MessageFeedback,
    ModeEvent,
    ModeStep,
    PartEvent,
    PlanEvent,
    PlanStepOut,
    RecordWidget,
    RememberedItem,
    ReplaceEvent,
    ReplyUsage,
    SignedIn,
    StatusEvent,
    TextEvent,
    ToolCall,
    ToolEndEvent,
    ToolGate,
    ToolStartEvent,
    WidgetEvent,
    WidgetPart,
)
from ops_contracts.skill_run import AGENT_TOOL_PREFIX, SkillRunState, hands_to_agent
from ops_service_kit.errors import Forbidden
from ops_service_kit.http import Json, JsonValue
from ops_service_kit.ids import now_iso
from ops_service_kit.narrow import json_list, json_object

from ..store.chat_list import ChatListQuery, unsummarised_rows
from ..store.chat_search import index_thread, indexed_ids, matching_threads
from ..store.events import EventLog, EventOut
from ..store.graphs import RunRow, StoredThread
from ..store.reviews import DecisionOut, ReviewStore
from ..store.tenancy import current_team
from ..store.thread_list import ThreadReader
from .auth import Principal, caller_of, graph_target, key_scope
from .chat_history import PLAN_PART
from .deps import Runtime
from .event_log import designed_type
from .memory import fill_remembered
from .review_text import call_label, input_rows, tool_titles
from .run_person import person_of_thread
from .runs import graph_store

CHAT_GRAPH = "agent_wrapper"
NEW_TITLE = "New chat"


def assistant_id(run_id: str) -> str:
    return f"m_{run_id.removeprefix('run_')}"


def _like(cap: str, value: Any) -> str:
    """A new cost cap written with the decimal places of the cap it replaces, so the card reads 7.50, not 7.500000."""
    try:
        places = max(0, -int(Decimal(cap).as_tuple().exponent))
        return f"{Decimal(str(value)):.{places}f}"
    except (InvalidOperation, ValueError, TypeError):
        return str(value)


# The quick reply that reruns a reply on the deeper model (routers/chat.py), and how many quick replies a reply holds.
THINK_HARDER = "Think harder"
# A call answered from what the chat already read, as its label says so in the call log.
EARLIER = ", from earlier in this chat"
MAX_FOLLOW_UPS = 3


def _worth_more_thought(m: ChatMessage) -> bool:
    """A reply that made a plan or two or more calls to a system: an ask a deeper model may answer better."""
    calls = [c for c in m.tool_calls or [] if c.server != "kernel"]
    return any(p.id == PLAN_PART for p in m.parts or []) or len(calls) >= 2


# The kernel's plan statuses (plan.py) as the plan frame names them: a blocked step is still the one being worked.
PLAN_STATUS: dict[str, Literal["pending", "doing", "done", "skipped"]] = {
    "todo": "pending",
    "doing": "doing",
    "blocked": "doing",
    "done": "done",
    "skipped": "skipped",
}


@dataclass
class AssistantBuilder:
    """One assistant message, built from one run's events."""

    catalog: Catalog
    message: ChatMessage
    decisions: dict[str, DecisionOut] = field(default_factory=dict[str, DecisionOut])
    # Approvers so far per call step, for a money call that needs two before it is decided.
    approvals: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    # Collect what a guardrail kept or took back (guardrail_audit): only for a reader allowed to view the audit, and
    # never on the live stream, whose message goes to the person who asked.
    audit: bool = False
    ended: bool = False
    # Plugin tools' titles (review_text.tool_titles), so a card names a tool as the tools list does.
    titles: dict[str, str] = field(default_factory=dict[str, str])
    # The parts the agent presented itself, as against the tables its tool calls drew.
    presented: set[str] = field(default_factory=set[str])
    # The alias Think harder reruns a reply on; a reply that made a plan or two calls, on another model, offers it.
    think_alias: str = ""
    # The ways of working the turn used, read from its turn event; the done frame carries them.
    modes: list[ModeStep] | None = None

    def _asked(self, call: ToolCall, c: Json) -> list[ChatStreamEvent]:
        """A call to a helper agent, as the person reads it: asked (started), then answered (finished)."""
        if not hands_to_agent(call.name):
            return []
        agent_id = call.name.removeprefix(AGENT_TOOL_PREFIX)
        a = self.catalog.agent(agent_id)
        out = json_object(c.get("output"))
        done = call.status != "running"
        answer = str(out.get("answer") or "") if done else ""
        return [
            AgentAskedEvent(
                agent_id=agent_id,
                agent_name=a.name if a is not None else str(out.get("agentName") or agent_id),
                question=str(json_object(c.get("input")).get("question") or ""),
                status="finished" if done else "started",
                summary=answer[:280] or None,
                call_id=call.id,
            )
        ]

    def _call(self, c: Json) -> ToolCall:
        status = str(c.get("status") or "")
        gated, output = None, c.get("output")
        definition = self.catalog.tool(str(c.get("tool")))
        if status == "gated":
            # A registry operation has no template: the gate is the approval itself, decided by a reviewer.
            tpl = definition.approval if definition else None
            gated = ToolGate(gate=tpl.gate if tpl else "Approval", reviewers=tpl.reviewers if tpl else "a reviewer")
            output = {"status": "awaiting_approval"}
        return ToolCall(
            id=str(c["id"]),
            name=str(c.get("tool")),
            label=f"{call_label(self.catalog, c, self.titles)}{EARLIER if c.get('cached') else ''}",
            server=str(c.get("server") or ""),
            input=json_object(c.get("input")),
            output=output,
            status="running" if status == "running" else "failed" if status == "error" else "success",
            duration_ms=int(cast(float | str, c.get("durationMs") or 0)),
            gated=gated,
            signed_in=SignedIn.model_validate(c["signedIn"]) if isinstance(c.get("signedIn"), dict) else None,
        )

    def _worded(self, text: str, tool: str) -> str:
        title = self.titles.get(tool)
        return text.replace(tool, title) if title and tool else text

    def _approval(self, interrupt: Json) -> ApprovalWidget:
        p = json_object(interrupt.get("payload"))
        definition = self.catalog.tool(str(p.get("tool")))
        tpl = definition.approval if definition else None
        args = json_object(p.get("input"))
        values = {k: str(v) for k, v in args.items()}
        decision = self.decisions.get(str(interrupt.get("id")))
        step = str(json_object(p.get("call")).get("step"))
        # The recorded decision is checked against the card's states, as the card's own validation did.
        state: ApprovalState = (
            _APPROVAL_STATE.validate_python(decision.decision)
            if decision
            else "awaiting_second"
            if self.approvals.get(step)
            else "pending"
        )
        return ApprovalWidget(
            id=approval_widget_id(str(interrupt.get("id"))),
            title=fill(tpl.title, values) if tpl else self.titles.get(str(p.get("tool"))) or str(p.get("tool")),
            app=str(p.get("server") or ""),
            tool=str(p.get("tool")),
            tool_label=call_label(self.catalog, {"tool": p.get("tool"), "input": p.get("input")}, self.titles),
            as_of=now_iso(),
            review_id=str(p.get("review_id")),
            action=self._worded(str(p.get("action") or ""), str(p.get("tool"))),
            # The kernel words the wait with the operation's name; a titled tool reads by its title there too.
            summary=fill(tpl.summary, values) if tpl else self._worded(str(p.get("needed") or ""), str(p.get("tool"))),
            # Without a template the reviewer sees every input the call will send, exactly as the model wrote it.
            # A row whose inputs the model left out says nothing, so it is left off rather than shown empty.
            fields=[
                LabelValue(label=label, value=value) for label, v in tpl.fields if (value := fill(v, values)).strip()
            ]
            if tpl
            else [LabelValue(**row) for row in input_rows(args)],
            risk=tpl.risk if tpl else "high",
            consequence=tpl.consequence if tpl else None,
            step_up=bool(p.get("step_up")) or None,
            ask_first=bool(p.get("ask_first")),
            state=state,
            decided_by=decision.decided_by if decision else None,
            reason=decision.reason if decision else None,
            waiting_on=None
            if decision
            else "your answer"
            if p.get("ask_first")
            else "a second approver"
            if state == "awaiting_second"
            else str(p.get("reviewers") or (tpl.reviewers if tpl else "") or "a reviewer"),
        )

    def apply(self, type_: str | None, data: Any, at: str | None = None) -> list[ChatStreamEvent]:
        m = self.message
        if at:
            m.at = at
        match type_:
            case "status":
                return [StatusEvent(phase=data)]
            case "text":
                m.content += str(data)
                return [TextEvent(delta=str(data))]
            case "text_replaced":
                # A guarded answer replaced after it streamed: the message keeps only the replacement.
                m.content = str(data)
                return [ReplaceEvent(text=str(data))]
            case "tool_call":
                call = self._call(json_object(data))
                if call.server == "kernel" and call.name != SEARCH_TOOL:
                    # The built-in present tool: the answer is the part, so no tool card is shown or kept. A search
                    # of the agent's own tools (search_tools) is shown like any call, so a person sees what it found.
                    view = json_object(data).get("view")
                    if (
                        view
                        and json_object(data).get("status") == "ok"
                        and isinstance(json_object(view).get("followUps"), list)
                    ):
                        # The reply's quick replies: the latest call's stand, at most three. A reply that asks or reads
                        # back for confirmation is answered by a tap, so the tables its reads drew give way, as they do
                        # for a presented card.
                        m.follow_ups = [str(r) for r in cast(list[Any], json_object(view)["followUps"])][:3]
                        m.parts = [p for p in m.parts or [] if p.id in self.presented] or None
                    if view and json_object(data).get("status") == "ok" and "part" in json_object(view):
                        # The plan is one part a turn, above the answer, that each plan call redraws.
                        planned = call.name == PLAN_TOOL
                        pid = PLAN_PART if planned else f"wp_{call.id}"
                        part = WidgetPart.model_validate({**json_object(json_object(view)["part"]), "id": pid})
                        self.presented.add(part.id)
                        kept = [p for p in m.parts or [] if p.id != part.id]
                        if planned:
                            m.parts = [part, *kept]
                            return [PartEvent(part=part)]
                        if part.kind is not None:
                            # A card the agent built from its reads takes the place of the tables those reads drew;
                            # the stored message the turn ends with (done) drops them from the screen too.
                            kept = [p for p in kept if p.id in self.presented]
                        m.parts = [*kept, part]
                        return [PartEvent(part=part)]
                    return []
                m.tool_calls = [*(c for c in m.tool_calls or [] if c.id != call.id), call]
                asked = self._asked(call, json_object(data))
                if call.status == "running":
                    return [ToolStartEvent(call=call), *asked]
                out: list[ChatStreamEvent] = [ToolEndEvent(call=call), *asked]
                view = json_object(data).get("view")
                if view and json_object(data).get("status") == "ok" and "part" in json_object(view):
                    # A shaped result (activities/shaper.py): its id is the call's, so a reload keeps the same one.
                    part = WidgetPart.model_validate({**json_object(json_object(view)["part"]), "id": f"wp_{call.id}"})
                    m.parts = [*(p for p in m.parts or [] if p.id != part.id), part]
                    out.append(PartEvent(part=part))
                elif view and json_object(data).get("status") == "ok":
                    widget = RecordWidget.model_validate(
                        {
                            **json_object(view),
                            "id": f"wg_{call.id}",
                            "app": call.server,
                            "tool": call.name,
                            "tool_label": call_label(
                                self.catalog, {"tool": call.name, "input": call.input}, self.titles
                            ),
                            "as_of": m.at,
                        }
                    )
                    m.widgets = [*(m.widgets or []), widget]
                    out.append(WidgetEvent(widget=widget))
                return out
            case "citation":
                m.citations = [Citation.model_validate(c) for c in cast(list[Any], data or [])]
                return [CitationsEvent(citations=m.citations)]
            case "memory":
                saved = cast(list[Any], json_object(data).get("saved") or [])
                m.remembered = [RememberedItem.model_validate(x) for x in saved] or None
                return []
            case "mode":
                d = json_object(data)
                return [ModeEvent.model_validate({k: d[k] for k in ("mode", "reason", "fixed")})]
            case "plan":
                d = json_object(data)
                steps = [
                    PlanStepOut(
                        id=str(i + 1),
                        text=str(json_object(s).get("title") or ""),
                        status=PLAN_STATUS.get(str(json_object(s).get("status")), "pending"),
                        note=cast(str | None, json_object(s).get("note")),
                    )
                    for i, s in enumerate(json_list(d.get("steps")))
                ]
                title = str(d.get("title") or "Plan")
                return [PlanEvent(title=title, steps=steps, revision=int(str(d.get("revision") or 0)))]
            case "skill_loaded":
                m.skills = [*(m.skills or []), LoadedSkill.model_validate(json_object(data))]
                return []
            case "skill_run":
                # The last one of the reply is the record the next reply goes on from.
                m.skill_run = SkillRunState.model_validate(json_object(data))
                return []
            case "guardrail_withheld" | "guardrail_retracted":
                if not self.audit:
                    return []
                d = json_object(data)
                entry = GuardrailAudit(
                    kind="withheld" if type_ == "guardrail_withheld" else "retracted",
                    text=str(d.get("text") or ""),
                    guardrail=GuardrailHit.model_validate(d["guardrail"]) if d.get("guardrail") else None,
                    stop_reason=cast(str | None, d.get("stopReason")),
                    at=at,
                )
                m.guardrail_audit = [*(m.guardrail_audit or []), entry]
                return []
            case "turn":
                d = json_object(data)
                self.modes = [ModeStep.model_validate(json_object(x)) for x in json_list(d.get("modes"))]
                # The turn event as the agent graph writes it: its fields are strings.
                m.model = cast(str | None, d.get("model"))
                if self.think_alias and m.model != self.think_alias and _worth_more_thought(m):
                    m.follow_ups = [*(m.follow_ups or [])[: MAX_FOLLOW_UPS - 1], THINK_HARDER]
                if d.get("noAnswer"):
                    m.no_answer = True
                if d.get("status") == "failed":
                    m.error = cast(str, d.get("error") or "The reply failed.")
                    m.error_code = cast(str | None, d.get("errorCode"))
                if d.get("guardrail"):
                    m.guardrail = GuardrailHit.model_validate(d["guardrail"])
                    m.content = str(d.get("text") or m.content)
                return []
            # A spent budget is logged as `waiting` (event_log.REVIEW_KINDS leaves it out): no review owns it.
            case "waiting" | "waiting_review" if (
                json_object(json_object(data).get("payload")).get("kind") == "budget_exhausted"
            ):
                p = json_object(json_object(data).get("payload"))
                m.budget = BudgetPause(
                    id=str(json_object(data).get("id") or "") or None,
                    limit=cast(Literal["calls", "tokens", "cost"], p.get("limit") or "calls"),
                    spent=str(p.get("spent")),
                    cap=str(p.get("cap")),
                )
                self.ended = True
                return []
            case "budget.answered":
                d = json_object(data)
                if m.budget is not None:
                    m.budget.state = "continued" if d.get("action") == "continue" else "raised"
                    m.budget.answered_by = str(d.get("by") or "")
                    caps = json_object(d.get("budget"))
                    m.budget.new_cap = (
                        _like(m.budget.cap, caps.get("maxCost"))
                        if m.budget.limit == "cost"
                        else str(caps.get("maxCalls"))
                    )
                return []
            case "waiting_review":
                widget = self._approval(json_object(data))
                m.widgets = [*(m.widgets or []), widget]
                out = [WidgetEvent(widget=widget)]
                if widget.ask_first:
                    # The person answers it on the card; no reviewer's gate is named on the held call.
                    m.tool_calls = [c.model_copy(update={"gated": None}) for c in m.tool_calls or []]
                    if not m.content.strip():
                        m.content = f"Before I change anything: {widget.action}. Allow it on the card below."
                        out.append(TextEvent(delta=m.content))
                elif not m.content.strip():
                    # The model went straight to the gated call; say what is waiting and for whom.
                    reviewers = str(json_object(json_object(data).get("payload")).get("reviewers") or "a reviewer")
                    m.content = f"I drafted this for review: {widget.action}. It runs once {reviewers} approve it."
                    out.append(TextEvent(delta=m.content))
                self.ended = True
                return out
            case "finished":
                self.ended = True
                return []
            case "failed":
                m.error = m.error or str(json_object(data).get("message") or "The reply failed.")
                self.ended = True
                return []
            case _:
                return []

    def apply_run_event(self, e: Json) -> list[ChatStreamEvent]:
        """A run-stream event (`{event, node, data}`), as `execute` yields it."""
        return self.apply(designed_type(e), e.get("data"))


def approval_widget_id(interrupt_id: str) -> str:
    return f"wg_{interrupt_id[:24]}"


_APPROVAL_STATE: TypeAdapter[ApprovalState] = TypeAdapter(ApprovalState)


async def decisions_of(rt: Runtime, thread_id: str) -> dict[str, DecisionOut]:
    return await ReviewStore(graph_store(rt).engine).decisions_of(thread_id)


async def approvals_of(rt: Runtime, thread_id: str) -> dict[str, list[str]]:
    return await ReviewStore(graph_store(rt).engine).approvals_by_step(thread_id)


async def messages_of(
    rt: Runtime, thread_ids: list[str], *, audit: bool = False, reader: str | None = None
) -> dict[str, list[ChatMessage]]:
    """Current (non-superseded) messages per thread, rebuilt from runs and events. What a guardrail kept back or took
    back (guardrail_audit) is left out unless `audit`, which only a caller allowed to view the audit may ask for. What
    a reply remembered carries its text only for `reader` when it is that memory's person (memory.fill_remembered)."""
    store = graph_store(rt)
    out: dict[str, list[ChatMessage]] = {}
    if not thread_ids:
        return out
    rows = await EventLog(store.engine).for_threads(thread_ids)
    by_thread: dict[str, list[EventOut]] = {t: [] for t in thread_ids}
    for r in rows:
        by_thread[r.thread_id].append(r)
    for tid in thread_ids:
        out[tid] = await _thread_messages(rt, tid, by_thread[tid], audit=audit)
    # A reply's memory event holds ids only; what was remembered is read from the memories as they are now.
    await fill_remembered(rt, [m for messages in out.values() for m in messages], reader)
    return out


async def _thread_messages(
    rt: Runtime, thread_id: str, events: list[EventOut], *, audit: bool = False
) -> list[ChatMessage]:
    runs = [r for r in await graph_store(rt).runs(thread_id) if r.kind in ("input", "resume", "recovery")]
    decisions = await decisions_of(rt, thread_id) if runs else {}
    approvals = await approvals_of(rt, thread_id) if runs else {}
    titles = await tool_titles(rt) if runs else {}
    per_run: dict[str, list[Any]] = {}
    superseded: set[str] = set()
    feedback: dict[str, JsonValue] = {}
    finished_children: dict[str, list[Any]] = {}
    for e in events:
        if e.type == "superseded":
            superseded |= set(cast(list[str], json_object(e.data).get("messageIds") or []))
        elif e.type == "child_finished":
            finished_children.setdefault(str(json_object(e.data).get("parentRunId")), []).append(e)
        elif e.type == "feedback":
            feedback[str(json_object(e.data).get("messageId"))] = json_object(e.data).get("feedback")
        elif e.run_id:
            per_run.setdefault(e.run_id, []).append(e)
    messages: list[ChatMessage] = []
    for run in runs:
        given = json_object(json_object(run.input).get("input"))
        if run.kind == "input" and given.get("user_message_id"):
            messages.append(
                ChatMessage.model_validate(
                    {
                        "id": given["user_message_id"],
                        "role": "user",
                        "content": str(given.get("message") or ""),
                        "at": run.created_at,
                        "attachments": given.get("attachments") or None,
                    }
                )
            )
        reply = ChatMessage(id=assistant_id(run.id), role="assistant", content="", at=run.created_at)
        if run.kind == "input" and given.get("settings"):
            reply.settings = EffectiveSettings.model_validate(given["settings"])
        if given.get("agent_id"):
            # Who answered, so a reload after a handover still credits the agent that wrote each reply.
            answered = rt.catalog.agent_in_flight(str(given["agent_id"]))
            reply.agent_id, reply.agent_name = str(given["agent_id"]), answered.name if answered else None
        builder = AssistantBuilder(
            rt.catalog,
            reply,
            decisions,
            approvals,
            audit=audit,
            titles=titles,
            think_alias=rt.settings.think_harder_alias,
        )
        for e in per_run.get(run.id, []):
            builder.apply(e.type, e.data, e.at)
        if not builder.ended and run.status != "running":
            reply.stopped = True  # the client left mid-reply, or the process died before the run ended
        if reply.content or reply.tool_calls or reply.widgets or reply.error or reply.budget or run.status == "running":
            messages.append(reply)
        for e in finished_children.get(run.id, []):
            d = json_object(e.data)
            name = str(d.get("workflow") or "").replace("_", " ")
            outcome = f": {d['outcome']}" if d.get("outcome") else ""
            content = f"The {name} workflow ({d.get('childThreadId')}) finished{outcome}."
            messages.append(ChatMessage(id=f"m_{d.get('childThreadId')}", role="assistant", content=content, at=e.at))
    for m in messages:
        if m.id in feedback:
            m.feedback = MessageFeedback.model_validate(feedback[m.id]) if feedback[m.id] else None
    await _with_usage(rt, thread_id, runs, messages)
    return [m for m in messages if m.id not in superseded]


async def _with_usage(rt: Runtime, thread_id: str, runs: list[RunRow], messages: list[ChatMessage]) -> None:
    """Each reply's model calls, tokens, cost and seconds, from one grouped read of the thread's model call
    records and the run's own start and finish."""
    if rt.usage is None or not runs:
        return
    totals = await rt.usage.totals_by_run(thread_id)
    by_reply = {assistant_id(r.id): r for r in runs}
    for m in messages:
        run = by_reply.get(m.id)
        spent = totals.get(run.id) if run is not None else None
        if run is None or spent is None or not spent.calls:
            continue
        started, finished = run.created_at, run.finished_at
        seconds = (
            round((datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds(), 1)
            if started and finished
            else None
        )
        m.usage = ReplyUsage(
            calls=spent.calls,
            input_tokens=spent.input_tokens,
            output_tokens=spent.output_tokens,
            cost=f"{spent.cost:.2f}",
            seconds=seconds,
        )


def thread_base(rt: Runtime, row: StoredThread, messages: list[ChatMessage]) -> Json:
    meta = json_object(row.meta)
    kb_ids = [str(k) for k in cast(list[Any], meta.get("kbIds") or [])]
    return {
        "id": row.id,
        "title": meta.get("title") or NEW_TITLE,
        "agent_id": meta.get("agentId"),
        "agent_name": meta.get("agentName"),
        "agent_version": meta.get("agentVersion") or 1,
        "kb_ids": [*kb_ids],
        # As kb-service named them when the thread opened; an older thread shows ids, never the seed's names.
        "kb_names": [str(n) for n in cast(list[Any], meta.get("kbNames") or [])] or [*kb_ids],
        "pinned": bool(meta.get("pinned")),
        "archived": bool(meta.get("archived")),
        "owner": meta.get("owner") or "",
        "created_at": row.created_at,
        "last_message_at": meta.get("lastMessageAt") or row.created_at,
        "message_count": len(messages),
        "start_agent_id": meta.get("startAgentId"),
        "start_agent_name": meta.get("startAgentName"),
        "test": bool(meta.get("test")),
    }


def thread_view(rt: Runtime, row: StoredThread, messages: list[ChatMessage]) -> ChatThread:
    return ChatThread.model_validate({**thread_base(rt, row, messages), "messages": messages})


def thread_row_view(rt: Runtime, row: StoredThread, messages: list[ChatMessage]) -> ChatThreadRow:
    last = next((m for m in reversed(messages) if m.content), None)
    return ChatThreadRow.model_validate(
        {
            **thread_base(rt, row, messages),
            "preview": (last.content if last else "").replace("**", "")[:140],
            "widgets": sum(len(m.widgets or []) for m in messages),
            "citations": sum(len(m.citations or []) for m in messages),
        }
    )


def owned_by(meta: Json, me: Principal) -> bool:
    """Whose chat this is: by the owner's email, recorded since chat reads became owner only; older threads by name."""
    email = meta.get("ownerEmail")
    return email == me.email if email else meta.get("owner") == me.name


def may_read(meta: Json, me: Principal) -> bool:
    """chat.view, which every built-in role holds for its own threads only (ops_access): the person who started the
    thread reads it, admins included; an API key reads none."""
    owner = str(meta.get("ownerEmail") or (me.email if meta.get("owner") == me.name else ""))
    try:
        can(caller_of(me), "chat", "view", owner=owner or "-", what="this conversation", from_any_team=True)
    except Forbidden:
        return False
    return True


def may_read_thread(row: Json, me: Principal) -> bool:
    """Any graph thread, for the thread and event routes: a scoped API key reaches its own target only; an agent's chat
    or a call it made for a person (the chat graph) is read under `may_read`, with the person it ran for as owner; any
    other thread by the team rule the store already applies."""
    scope = key_scope(me)
    if scope is not None and graph_target(str(row["graph"])) != scope:
        return False
    person = person_of_thread(row)
    meta = json_object(row["meta"])
    # A run-API thread of the chat graph that names no person (no chat, no owner, started for nobody) is the team's.
    if person is None or not (person.email or meta.get("chat") or meta.get("owner")):
        return True
    return may_read({**meta, "ownerEmail": person.email} if person.email else meta, me)


def thread_reader(me: Principal) -> ThreadReader:
    """`may_read_thread`'s caller half, worked out once for a list (`store.thread_list.readable` is its row half): a
    scoped key's one graph, and chat.view for anyone's thread (`all`) or the caller's own (`own`), each probed through
    `can` as a row would ask it, so the dev caller, a key and a custom role answer as they do there."""
    scope = key_scope(me)
    graphs: tuple[str, ...] | None = None
    if scope is not None:
        kind, target = scope
        graph = f"agent:{target}" if kind == "agent" else target
        graphs = (graph,) if graph_target(graph) == scope else ()
    chat: Literal["none", "own", "all"] = "none"
    if may_read({"ownerEmail": "-"}, me):
        chat = "all"
    elif may_read({"ownerEmail": me.email}, me):
        chat = "own"
    return ThreadReader(graphs=graphs, chat=chat, email=me.email.strip().lower(), name=me.name)


async def chat_rows(rt: Runtime, me: Principal) -> list[StoredThread]:
    """The caller's own visible chat threads (`may_read`)."""
    rows = await graph_store(rt).thread_rows(CHAT_GRAPH)
    return [
        r
        for r in rows
        if json_object(r.meta).get("chat")
        and not json_object(r.meta).get("hidden")
        and may_read(json_object(r.meta), me)
    ]


async def chat_row(rt: Runtime, thread_id: str, me: Principal | None) -> StoredThread | None:
    """One visible chat thread by id: the caller's own, so anyone else, a teammate included, reads it as not found.
    `me=None` skips the owner rule for a review decision made from the thread, which the review policy authorises; the
    team rule still applies."""
    row = await graph_store(rt).thread_row(thread_id)
    if (
        row is None
        or row.graph != CHAT_GRAPH
        or not json_object(row.meta).get("chat")
        or json_object(row.meta).get("hidden")
    ):
        return None
    if (team := current_team()) is not None and row.team_id != team:
        return None
    if me is not None and not may_read(json_object(row.meta), me):
        return None
    return row


async def update_meta(rt: Runtime, thread_id: str, **patch: Any) -> None:
    await graph_store(rt).merge_meta(thread_id, patch, updated_at=now_iso())


def summary(messages: list[ChatMessage]) -> Json:
    """What a thread list reads from meta instead of rebuilding the messages; kept current after every turn."""
    last = next((m for m in reversed(messages) if m.content), None)
    return {
        "preview": (last.content if last else "").replace("**", "")[:140],
        "messageCount": len(messages),
    }


async def index_chat(rt: Runtime, row: StoredThread, messages: list[ChatMessage]) -> None:
    """The thread's search row: title, agent, last reply and every question, as plain columns (store/chat_search)."""
    meta = json_object(row.meta)
    await index_thread(
        graph_store(rt).engine,
        {
            "thread_id": row.id,
            "team_id": row.team_id,
            "title": str(meta.get("title") or NEW_TITLE),
            "agent_name": str(meta.get("agentName") or ""),
            "preview": summary(messages)["preview"],
            "questions": "\n".join(m.content for m in messages if m.role == "user"),
            "updated_at": now_iso(),
        },
    )


async def store_summary(rt: Runtime, thread_id: str) -> None:
    """After a turn or a rename: the list's summary in meta and the thread's search row."""
    messages = (await messages_of(rt, [thread_id]))[thread_id]
    await update_meta(rt, thread_id, **summary(messages))
    if (row := await graph_store(rt).thread_row(thread_id)) is not None:
        await index_chat(rt, row, messages)


BACKFILL_BATCH = 100


async def with_stored_summaries(rt: Runtime, owner_email: str, owner_name: str) -> None:
    """`with_summaries` for the caller's own threads that need it, found in SQL a batch at a time, so a list reads no
    other person's thread and a long history fills in over a few lists."""
    q = ChatListQuery(graph=CHAT_GRAPH, owner_email=owner_email, owner_name=owner_name)
    rows = await unsummarised_rows(graph_store(rt).engine, q, limit=BACKFILL_BATCH)
    await with_summaries(rt, rows)


async def with_summaries(rt: Runtime, rows: list[StoredThread]) -> None:
    """Threads written before summaries or search rows were kept get them once, here, so later lists read meta only
    and search reads its own columns."""
    indexed = await indexed_ids(graph_store(rt).engine, [r.id for r in rows])
    missing = [r for r in rows if "messageCount" not in json_object(r.meta) or r.id not in indexed]
    if not missing:
        return
    msgs = await messages_of(rt, [r.id for r in missing])
    for r in missing:
        rid = r.id
        s = summary(msgs[rid])
        r.meta = {**json_object(r.meta), **s}
        await update_meta(rt, rid, **s)
        await index_chat(rt, r, msgs[rid])


async def matching_ids(rt: Runtime, search: str) -> set[str]:
    """Chat threads whose title, agent, last reply or any question the person asked contains `search`."""
    return await matching_threads(graph_store(rt).engine, search)
