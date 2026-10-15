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
from typing import Any, cast

from ops_agents.activities.catalog import Catalog
from ops_agents.activities.tools import fill
from ops_contracts.chat import (
    ApprovalWidget,
    ChatMessage,
    ChatStreamEvent,
    ChatThread,
    ChatThreadRow,
    Citation,
    CitationsEvent,
    LabelValue,
    MessageFeedback,
    RecordWidget,
    StatusEvent,
    TextEvent,
    ToolCall,
    ToolEndEvent,
    ToolGate,
    ToolStartEvent,
    WidgetEvent,
)
from ops_service_kit.ids import now_iso

from ..store.events import EventLog
from ..store.reviews import ReviewStore
from .deps import Runtime
from .event_log import designed_type
from .runs import graph_store

CHAT_GRAPH = "agent_wrapper"
NEW_TITLE = "New chat"


def assistant_id(run_id: str) -> str:
    return f"m_{run_id.removeprefix('run_')}"


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
            as_of=now_iso(),
            review_id=str(p.get("review_id")),
            action=str(p.get("action") or ""),
            summary=fill(tpl.summary, values) if tpl else str(p.get("needed") or ""),
            # Without a template the reviewer sees every input the call will send, exactly as the model wrote it.
            fields=[LabelValue(label=label, value=fill(v, values)) for label, v in tpl.fields]
            if tpl
            else [LabelValue(label=k, value=v) for k, v in values.items()],
            risk=tpl.risk if tpl else "high",
            consequence=tpl.consequence if tpl else None,
            step_up=bool(p.get("step_up")) or None,
            state=state,
            decided_by=decision["decided_by"] if decision else None,
            reason=decision["reason"] if decision else None,
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
            case "tool_call":
                call = self._call(_d(data))
                m.tool_calls = [*(c for c in m.tool_calls or [] if c.id != call.id), call]
                if call.status == "running":
                    return [ToolStartEvent(call=call)]
                out: list[ChatStreamEvent] = [ToolEndEvent(call=call)]
                view = _d(data).get("view")
                if view and _d(data).get("status") == "ok":
                    widget = RecordWidget.model_validate(
                        {**_d(view), "id": f"wg_{call.id}", "app": call.server, "tool": call.name, "as_of": m.at}
                    )
                    m.widgets = [*(m.widgets or []), widget]
                    out.append(WidgetEvent(widget=widget))
                return out
            case "citation":
                m.citations = [Citation.model_validate(c) for c in cast(list[Any], data or [])]
                return [CitationsEvent(citations=m.citations)]
            case "turn":
                d = _d(data)
                m.model = d.get("model")
                if d.get("noAnswer"):
                    m.no_answer = True
                if d.get("status") == "failed":
                    m.error = d.get("error") or "The reply failed."
                    m.error_code = d.get("errorCode")
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


async def messages_of(rt: Runtime, thread_ids: list[str]) -> dict[str, list[ChatMessage]]:
    """Current (non-superseded) messages per thread, rebuilt from runs and events."""
    store = graph_store(rt)
    out: dict[str, list[ChatMessage]] = {}
    if not thread_ids:
        return out
    rows = await EventLog(store.engine).for_threads(thread_ids)
    by_thread: dict[str, list[Any]] = {t: [] for t in thread_ids}
    for r in rows:
        by_thread[r.thread_id].append(r)
    for tid in thread_ids:
        out[tid] = await _thread_messages(rt, tid, by_thread[tid])
    return out


async def _thread_messages(rt: Runtime, thread_id: str, events: list[Any]) -> list[ChatMessage]:
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
        builder = AssistantBuilder(rt.catalog, reply, decisions, approvals)
        for e in per_run.get(run["id"], []):
            builder.apply(e.type, e.data, e.at)
        if not builder.ended and run["status"] != "running":
            reply.stopped = True  # the client left mid-reply, or the process died before the run ended
        if reply.content or reply.tool_calls or reply.widgets or reply.error or run["status"] == "running":
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
    return [m for m in messages if m.id not in superseded]


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
        "kb_names": [rt.catalog.kb_name(k) for k in kb_ids],
        "pinned": bool(meta.get("pinned")),
        "archived": bool(meta.get("archived")),
        "owner": meta.get("owner") or "",
        "created_at": row["created_at"],
        "last_message_at": meta.get("lastMessageAt") or row["created_at"],
        "message_count": len(messages),
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


async def chat_rows(rt: Runtime) -> list[dict[str, Any]]:
    """Visible chat threads: agent wrapper threads the chat facade created and nobody deleted."""
    rows = await graph_store(rt).threads(CHAT_GRAPH)
    return [r for r in rows if _d(r["meta"]).get("chat") and not _d(r["meta"]).get("hidden")]


async def chat_row(rt: Runtime, thread_id: str) -> dict[str, Any] | None:
    row = await graph_store(rt).thread(thread_id)
    if row is None or row["graph"] != CHAT_GRAPH or not _d(row["meta"]).get("chat") or _d(row["meta"]).get("hidden"):
        return None
    return row


async def update_meta(rt: Runtime, thread_id: str, **patch: Any) -> None:
    await graph_store(rt).merge_meta(thread_id, patch, updated_at=now_iso())
