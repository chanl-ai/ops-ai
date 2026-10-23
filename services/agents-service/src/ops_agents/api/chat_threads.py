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
from typing import Any, cast

from ops_access import can
from ops_agent_kernel.search import NAME as SEARCH_TOOL
from ops_agents.activities.catalog import Catalog
from ops_agents.activities.tools import fill
from ops_contracts.chat import (
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
    PartEvent,
    RecordWidget,
    RememberedItem,
    ReplaceEvent,
    ReplyUsage,
    StatusEvent,
    TextEvent,
    ToolCall,
    ToolEndEvent,
    ToolGate,
    ToolStartEvent,
    WidgetEvent,
    WidgetPart,
)
from ops_service_kit.errors import Forbidden
from ops_service_kit.ids import now_iso

from ..store.chat_search import index_thread, indexed_ids, matching_threads
from ..store.events import EventLog
from ..store.reviews import ReviewStore
from ..store.tenancy import current_team
from .auth import Principal, caller_of
from .deps import Runtime
from .event_log import designed_type
from .review_text import call_label
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


def _d(v: Any) -> dict[str, Any]:
    return cast(dict[str, Any], v) if isinstance(v, dict) else {}


@dataclass
class AssistantBuilder:
    """One assistant message, built from one run's events."""

    catalog: Catalog
    message: ChatMessage
    decisions: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    # Approvers so far per call step, for a money call that needs two before it is decided.
    approvals: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    # Collect what a guardrail kept or took back (guardrail_audit): only for a reader allowed to view the audit, and
    # never on the live stream, whose message goes to the person who asked.
    audit: bool = False
    ended: bool = False

    def _call(self, c: dict[str, Any]) -> ToolCall:
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
            server=str(c.get("server") or ""),
            input=_d(c.get("input")),
            output=output,
            status="running" if status == "running" else "failed" if status == "error" else "success",
            duration_ms=int(c.get("durationMs") or 0),
            gated=gated,
        )

    def _approval(self, interrupt: dict[str, Any]) -> ApprovalWidget:
        p = _d(interrupt.get("payload"))
        definition = self.catalog.tool(str(p.get("tool")))
        tpl = definition.approval if definition else None
        values = {k: str(v) for k, v in _d(p.get("input")).items()}
        decision = self.decisions.get(str(interrupt.get("id")))
        step = str(_d(p.get("call")).get("step"))
        state = decision["decision"] if decision else "awaiting_second" if self.approvals.get(step) else "pending"
        return ApprovalWidget(
            id=approval_widget_id(str(interrupt.get("id"))),
            title=fill(tpl.title, values) if tpl else str(p.get("tool")),
            app=str(p.get("server") or ""),
            tool=str(p.get("tool")),
            tool_label=call_label(self.catalog, {"tool": p.get("tool"), "input": p.get("input")}),
            as_of=now_iso(),
            review_id=str(p.get("review_id")),
            action=str(p.get("action") or ""),
            summary=fill(tpl.summary, values) if tpl else str(p.get("needed") or ""),
            # Without a template the reviewer sees every input the call will send, exactly as the model wrote it.
            # A row whose inputs the model left out says nothing, so it is left off rather than shown empty.
            fields=[
                LabelValue(label=label, value=value) for label, v in tpl.fields if (value := fill(v, values)).strip()
            ]
            if tpl
            else [LabelValue(label=k, value=v) for k, v in values.items()],
            risk=tpl.risk if tpl else "high",
            consequence=tpl.consequence if tpl else None,
            step_up=bool(p.get("step_up")) or None,
            state=state,
            decided_by=decision["decided_by"] if decision else None,
            reason=decision["reason"] if decision else None,
            waiting_on=None
            if decision
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
                call = self._call(_d(data))
                if call.server == "kernel" and call.name != SEARCH_TOOL:
                    # The built-in present tool: the answer is the part, so no tool card is shown or kept. A search
                    # of the agent's own tools (search_tools) is shown like any call, so a person sees what it found.
                    view = _d(data).get("view")
                    if view and _d(data).get("status") == "ok" and "part" in _d(view):
                        part = WidgetPart.model_validate({**_d(_d(view)["part"]), "id": f"wp_{call.id}"})
                        m.parts = [*(p for p in m.parts or [] if p.id != part.id), part]
                        return [PartEvent(part=part)]
                    return []
                m.tool_calls = [*(c for c in m.tool_calls or [] if c.id != call.id), call]
                if call.status == "running":
                    return [ToolStartEvent(call=call)]
                out: list[ChatStreamEvent] = [ToolEndEvent(call=call)]
                view = _d(data).get("view")
                if view and _d(data).get("status") == "ok" and "part" in _d(view):
                    # A shaped result (activities/shaper.py): its id is the call's, so a reload keeps the same one.
                    part = WidgetPart.model_validate({**_d(_d(view)["part"]), "id": f"wp_{call.id}"})
                    m.parts = [*(p for p in m.parts or [] if p.id != part.id), part]
                    out.append(PartEvent(part=part))
                elif view and _d(data).get("status") == "ok":
                    widget = RecordWidget.model_validate(
                        {
                            **_d(view),
                            "id": f"wg_{call.id}",
                            "app": call.server,
                            "tool": call.name,
                            "tool_label": call_label(self.catalog, {"tool": call.name, "input": call.input}),
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
                saved = cast(list[Any], _d(data).get("saved") or [])
                m.remembered = [RememberedItem.model_validate(x) for x in saved] or None
                return []
            case "skill_loaded":
                m.skills = [*(m.skills or []), LoadedSkill.model_validate(_d(data))]
                return []
            case "guardrail_withheld" | "guardrail_retracted":
                if not self.audit:
                    return []
                d = _d(data)
                entry = GuardrailAudit(
                    kind="withheld" if type_ == "guardrail_withheld" else "retracted",
                    text=str(d.get("text") or ""),
                    guardrail=GuardrailHit.model_validate(d["guardrail"]) if d.get("guardrail") else None,
                    stop_reason=d.get("stopReason"),
                    at=at,
                )
                m.guardrail_audit = [*(m.guardrail_audit or []), entry]
                return []
            case "turn":
                d = _d(data)
                m.model = d.get("model")
                if d.get("noAnswer"):
                    m.no_answer = True
                if d.get("status") == "failed":
                    m.error = d.get("error") or "The reply failed."
                    m.error_code = d.get("errorCode")
                if d.get("guardrail"):
                    m.guardrail = GuardrailHit.model_validate(d["guardrail"])
                    m.content = str(d.get("text") or m.content)
                return []
            # A spent budget is logged as `waiting` (event_log.REVIEW_KINDS leaves it out): no review owns it.
            case "waiting" | "waiting_review" if _d(_d(data).get("payload")).get("kind") == "budget_exhausted":
                p = _d(_d(data).get("payload"))
                m.budget = BudgetPause(
                    id=str(_d(data).get("id") or "") or None,
                    limit=p.get("limit") or "calls",
                    spent=str(p.get("spent")),
                    cap=str(p.get("cap")),
                )
                self.ended = True
                return []
            case "budget.answered":
                d = _d(data)
                if m.budget is not None:
                    m.budget.state = "continued" if d.get("action") == "continue" else "raised"
                    m.budget.answered_by = str(d.get("by") or "")
                    caps = _d(d.get("budget"))
                    m.budget.new_cap = (
                        _like(m.budget.cap, caps.get("maxCost"))
                        if m.budget.limit == "cost"
                        else str(caps.get("maxCalls"))
                    )
                return []
            case "waiting_review":
                widget = self._approval(_d(data))
                m.widgets = [*(m.widgets or []), widget]
                out = [WidgetEvent(widget=widget)]
                if not m.content.strip():
                    # The model went straight to the gated call; say what is waiting and for whom.
                    reviewers = str(_d(_d(data).get("payload")).get("reviewers") or "a reviewer")
                    m.content = f"I drafted this for review: {widget.action}. It runs once {reviewers} approve it."
                    out.append(TextEvent(delta=m.content))
                self.ended = True
                return out
            case "finished":
                self.ended = True
                return []
            case "failed":
                m.error = m.error or str(_d(data).get("message") or "The reply failed.")
                self.ended = True
                return []
            case _:
                return []

    def apply_run_event(self, e: dict[str, Any]) -> list[ChatStreamEvent]:
        """A run-stream event (`{event, node, data}`), as `execute` yields it."""
        return self.apply(designed_type(e), e.get("data"))


def approval_widget_id(interrupt_id: str) -> str:
    return f"wg_{interrupt_id[:24]}"


async def decisions_of(rt: Runtime, thread_id: str) -> dict[str, dict[str, Any]]:
    return await ReviewStore(graph_store(rt).engine).decisions_of(thread_id)


async def approvals_of(rt: Runtime, thread_id: str) -> dict[str, list[str]]:
    return await ReviewStore(graph_store(rt).engine).approvals_by_step(thread_id)


async def messages_of(rt: Runtime, thread_ids: list[str], *, audit: bool = False) -> dict[str, list[ChatMessage]]:
    """Current (non-superseded) messages per thread, rebuilt from runs and events. What a guardrail kept back or took
    back (guardrail_audit) is left out unless `audit`, which only a caller allowed to view the audit may ask for."""
    store = graph_store(rt)
    out: dict[str, list[ChatMessage]] = {}
    if not thread_ids:
        return out
    rows = await EventLog(store.engine).for_threads(thread_ids)
    by_thread: dict[str, list[Any]] = {t: [] for t in thread_ids}
    for r in rows:
        by_thread[r.thread_id].append(r)
    for tid in thread_ids:
        out[tid] = await _thread_messages(rt, tid, by_thread[tid], audit=audit)
    return out


async def _thread_messages(rt: Runtime, thread_id: str, events: list[Any], *, audit: bool = False) -> list[ChatMessage]:
    runs = [r for r in await graph_store(rt).runs(thread_id) if r["kind"] in ("input", "resume", "recovery")]
    decisions = await decisions_of(rt, thread_id) if runs else {}
    approvals = await approvals_of(rt, thread_id) if runs else {}
    per_run: dict[str, list[Any]] = {}
    superseded: set[str] = set()
    feedback: dict[str, dict[str, Any] | None] = {}
    finished_children: dict[str, list[Any]] = {}
    for e in events:
        if e.type == "superseded":
            superseded |= set(_d(e.data).get("messageIds") or [])
        elif e.type == "child_finished":
            finished_children.setdefault(str(_d(e.data).get("parentRunId")), []).append(e)
        elif e.type == "feedback":
            feedback[str(_d(e.data).get("messageId"))] = _d(e.data).get("feedback")
        elif e.run_id:
            per_run.setdefault(e.run_id, []).append(e)
    messages: list[ChatMessage] = []
    for run in runs:
        given = _d(_d(run["input"]).get("input"))
        if run["kind"] == "input" and given.get("user_message_id"):
            messages.append(
                ChatMessage.model_validate(
                    {
                        "id": given["user_message_id"],
                        "role": "user",
                        "content": str(given.get("message") or ""),
                        "at": run["created_at"],
                        "attachments": given.get("attachments") or None,
                    }
                )
            )
        reply = ChatMessage(id=assistant_id(run["id"]), role="assistant", content="", at=run["created_at"])
        if run["kind"] == "input" and given.get("settings"):
            reply.settings = EffectiveSettings.model_validate(given["settings"])
        if given.get("agent_id"):
            # Who answered, so a reload after a handover still credits the agent that wrote each reply.
            answered = rt.catalog.agent_in_flight(str(given["agent_id"]))
            reply.agent_id, reply.agent_name = str(given["agent_id"]), answered.name if answered else None
        builder = AssistantBuilder(rt.catalog, reply, decisions, approvals, audit=audit)
        for e in per_run.get(run["id"], []):
            builder.apply(e.type, e.data, e.at)
        if not builder.ended and run["status"] != "running":
            reply.stopped = True  # the client left mid-reply, or the process died before the run ended
        if (
            reply.content
            or reply.tool_calls
            or reply.widgets
            or reply.error
            or reply.budget
            or run["status"] == "running"
        ):
            messages.append(reply)
        for e in finished_children.get(run["id"], []):
            d = _d(e.data)
            name = str(d.get("workflow") or "").replace("_", " ")
            outcome = f": {d['outcome']}" if d.get("outcome") else ""
            content = f"The {name} workflow ({d.get('childThreadId')}) finished{outcome}."
            messages.append(ChatMessage(id=f"m_{d.get('childThreadId')}", role="assistant", content=content, at=e.at))
    for m in messages:
        if m.id in feedback:
            m.feedback = MessageFeedback.model_validate(feedback[m.id]) if feedback[m.id] else None
    await _with_usage(rt, thread_id, runs, messages)
    return [m for m in messages if m.id not in superseded]


async def _with_usage(rt: Runtime, thread_id: str, runs: list[dict[str, Any]], messages: list[ChatMessage]) -> None:
    """Each reply's model calls, tokens, cost and seconds (c-286), from one grouped read of the thread's model call
    records and the run's own start and finish."""
    if rt.usage is None or not runs:
        return
    totals = await rt.usage.totals_by_run(thread_id)
    by_reply = {assistant_id(r["id"]): r for r in runs}
    for m in messages:
        run = by_reply.get(m.id)
        spent = totals.get(run["id"]) if run is not None else None
        if run is None or spent is None or not spent.calls:
            continue
        started, finished = run.get("created_at"), run.get("finished_at")
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


def thread_base(rt: Runtime, row: dict[str, Any], messages: list[ChatMessage]) -> dict[str, Any]:
    meta = _d(row["meta"])
    kb_ids = [str(k) for k in cast(list[Any], meta.get("kbIds") or [])]
    return {
        "id": row["id"],
        "title": meta.get("title") or NEW_TITLE,
        "agent_id": meta.get("agentId"),
        "agent_name": meta.get("agentName"),
        "agent_version": meta.get("agentVersion") or 1,
        "kb_ids": kb_ids,
        # As kb-service named them when the thread opened; an older thread shows ids, never the seed's names.
        "kb_names": [str(n) for n in cast(list[Any], meta.get("kbNames") or [])] or kb_ids,
        "pinned": bool(meta.get("pinned")),
        "archived": bool(meta.get("archived")),
        "owner": meta.get("owner") or "",
        "created_at": row["created_at"],
        "last_message_at": meta.get("lastMessageAt") or row["created_at"],
        "message_count": len(messages),
        "start_agent_id": meta.get("startAgentId"),
        "start_agent_name": meta.get("startAgentName"),
        "test": bool(meta.get("test")),
    }


def thread_view(rt: Runtime, row: dict[str, Any], messages: list[ChatMessage]) -> ChatThread:
    return ChatThread.model_validate({**thread_base(rt, row, messages), "messages": messages})


def thread_row_view(rt: Runtime, row: dict[str, Any], messages: list[ChatMessage]) -> ChatThreadRow:
    last = next((m for m in reversed(messages) if m.content), None)
    return ChatThreadRow.model_validate(
        {
            **thread_base(rt, row, messages),
            "preview": (last.content if last else "").replace("**", "")[:140],
            "widgets": sum(len(m.widgets or []) for m in messages),
            "citations": sum(len(m.citations or []) for m in messages),
        }
    )


def owned_by(meta: dict[str, Any], me: Principal) -> bool:
    """Whose chat this is: by the owner's email, recorded since chat reads became owner only; older threads by name."""
    email = meta.get("ownerEmail")
    return email == me.email if email else meta.get("owner") == me.name


def may_read(meta: dict[str, Any], me: Principal) -> bool:
    """chat.view, which every built-in role holds for its own threads only (ops_access): the person who started the
    thread reads it, admins included; an API key reads none."""
    owner = str(meta.get("ownerEmail") or (me.email if meta.get("owner") == me.name else ""))
    try:
        can(caller_of(me), "chat", "view", owner=owner or "-", what="this conversation", from_any_team=True)
    except Forbidden:
        return False
    return True


async def chat_rows(rt: Runtime, me: Principal) -> list[dict[str, Any]]:
    """The caller's own visible chat threads (`may_read`)."""
    rows = await graph_store(rt).threads(CHAT_GRAPH)
    return [
        r for r in rows if _d(r["meta"]).get("chat") and not _d(r["meta"]).get("hidden") and may_read(_d(r["meta"]), me)
    ]


async def chat_row(rt: Runtime, thread_id: str, me: Principal | None) -> dict[str, Any] | None:
    """One visible chat thread by id: the caller's own, so anyone else, a teammate included, reads it as not found.
    `me=None` skips the owner rule for a review decision made from the thread, which the review policy authorises; the
    team rule still applies."""
    row = await graph_store(rt).thread(thread_id)
    if row is None or row["graph"] != CHAT_GRAPH or not _d(row["meta"]).get("chat") or _d(row["meta"]).get("hidden"):
        return None
    if (team := current_team()) is not None and row["team_id"] != team:
        return None
    if me is not None and not may_read(_d(row["meta"]), me):
        return None
    return row


async def update_meta(rt: Runtime, thread_id: str, **patch: Any) -> None:
    await graph_store(rt).merge_meta(thread_id, patch, updated_at=now_iso())


def summary(messages: list[ChatMessage]) -> dict[str, Any]:
    """What a thread list reads from meta instead of rebuilding the messages; kept current after every turn."""
    last = next((m for m in reversed(messages) if m.content), None)
    return {
        "preview": (last.content if last else "").replace("**", "")[:140],
        "messageCount": len(messages),
    }


async def index_chat(rt: Runtime, row: dict[str, Any], messages: list[ChatMessage]) -> None:
    """The thread's search row: title, agent, last reply and every question, as plain columns (store/chat_search)."""
    meta = _d(row["meta"])
    await index_thread(
        graph_store(rt).engine,
        {
            "thread_id": row["id"],
            "team_id": row["team_id"],
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
    if (row := await graph_store(rt).thread(thread_id)) is not None:
        await index_chat(rt, row, messages)


async def with_summaries(rt: Runtime, rows: list[dict[str, Any]]) -> None:
    """Threads written before summaries or search rows were kept get them once, here, so later lists read meta only
    and search reads its own columns."""
    indexed = await indexed_ids(graph_store(rt).engine, [r["id"] for r in rows])
    missing = [r for r in rows if "messageCount" not in _d(r["meta"]) or r["id"] not in indexed]
    if not missing:
        return
    msgs = await messages_of(rt, [r["id"] for r in missing])
    for r in missing:
        s = summary(msgs[r["id"]])
        r["meta"] = {**_d(r["meta"]), **s}
        await update_meta(rt, r["id"], **s)
        await index_chat(rt, r, msgs[r["id"]])


async def matching_ids(rt: Runtime, search: str) -> set[str]:
    """Chat threads whose title, agent, last reply or any question the person asked contains `search`."""
    return await matching_threads(graph_store(rt).engine, search)
