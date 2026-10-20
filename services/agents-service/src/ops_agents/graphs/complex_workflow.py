# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# langgraph.graph ships without complete type information (no stubs; StateGraph.add_node is partially Unknown).
"""Workflow "Dispute email": classify, fan out over attachments, extract each, collect, draft, grade and redraft
until the grade passes or three attempts, a human review, then send the reply or close.

Fan-out uses LangGraph's Send; concurrency is capped by the run's `max_concurrency` (4, set by the API), which is
LangGraph's own limit, so no semaphore lives in state."""

from __future__ import annotations

import asyncio
import hashlib
import operator
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send, interrupt

from ops_service_kit.ids import canonical_json

from .common import GraphDeps, approval_token, emit, reply_call

LABELS = ["card_dispute", "complaint", "other"]
MAX_ATTACHMENTS = 20
MAX_ATTEMPTS = 3
PASS_SCORE = 0.8


class Attachment(TypedDict):
    name: str
    # The text inline, or a file id whose text the files service holds; channels send references (E4, E6).
    text: NotRequired[str]
    file_id: NotRequired[str]


class Email(TypedDict):
    sender: str
    subject: str
    body: str
    attachments: list[Attachment]


class DisputeState(TypedDict):
    email: Email
    # Scores used in place of the judge for the first attempts; lets a test or a demo force the redraft loop.
    grade_overrides: NotRequired[list[float]]
    # Holds each extract this long before its model call; lets a test or a demo kill a process mid-node.
    extract_delay_ms: NotRequired[int]
    category: NotRequired[str]
    attachments: NotRequired[list[Attachment]]
    dropped_attachments: NotRequired[int]
    extractions: Annotated[list[dict[str, Any]], operator.add]
    evidence: NotRequired[str]
    draft: NotRequired[str]
    attempts: NotRequired[int]
    score: NotRequired[float]
    feedback: NotRequired[str]
    review_id: NotRequired[str]
    decision: NotRequired[dict[str, Any]]
    sent: NotRequired[str]
    status: NotRequired[str]


class ExtractTask(TypedDict):
    category: str
    attachment: Attachment
    delay_ms: int


def _email_text(e: Email) -> str:
    return f"From: {e['sender']}\nSubject: {e['subject']}\n\n{e['body']}"


def build(deps: GraphDeps, checkpointer: BaseCheckpointSaver[Any] | None) -> CompiledStateGraph[Any, Any, Any, Any]:
    async def classify(state: DisputeState) -> dict[str, Any]:
        atts = state["email"]["attachments"]
        category = await deps.models.classify(_email_text(state["email"]), LABELS)
        return {
            "category": category,
            "attachments": atts[:MAX_ATTACHMENTS],
            "dropped_attachments": max(0, len(atts) - MAX_ATTACHMENTS),
        }

    def fan_out(state: DisputeState) -> list[Send] | Literal["collect"]:
        atts = state.get("attachments") or []
        if not atts:
            return "collect"
        delay = state.get("extract_delay_ms", 0)
        return [
            Send("extract", ExtractTask(category=state.get("category", "other"), attachment=a, delay_ms=delay))
            for a in atts
        ]

    async def extract(task: ExtractTask) -> dict[str, Any]:
        a = task["attachment"]
        if task["delay_ms"]:
            await asyncio.sleep(task["delay_ms"] / 1000)
        text = a.get("text")
        if text is None:
            if deps.files is None or "file_id" not in a:
                raise ValueError(f"attachment {a['name']} has neither text nor a readable file id")
            text = await deps.files.read_file(a["file_id"])
        facts = await deps.models.extract(task["category"], a["name"], text)
        return {"extractions": [{"name": a["name"], **facts.model_dump(exclude_none=True)}]}

    async def collect(state: DisputeState) -> dict[str, Any]:
        rows = sorted(state["extractions"], key=lambda x: str(x["name"]))
        evidence = "\n".join(f"- {r['name']}: {r.get('summary', '')}" for r in rows)
        return {"evidence": evidence or "No attachments."}

    async def draft(state: DisputeState) -> dict[str, Any]:
        attempts = state.get("attempts", 0) + 1
        text = await deps.models.draft(_email_text(state["email"]), state.get("evidence", ""), state.get("feedback"))
        emit("text", "draft", text)
        return {"draft": text, "attempts": attempts}

    async def grade(state: DisputeState) -> dict[str, Any]:
        attempts = state.get("attempts", 1)
        overrides = state.get("grade_overrides") or []
        if attempts <= len(overrides):
            return {
                "score": overrides[attempts - 1],
                "feedback": "Seeded grade: make the next step and timeline explicit.",
            }
        g = await deps.models.grade(_email_text(state["email"]), state.get("draft", ""))
        return {"score": g.score, "feedback": g.feedback}

    def after_grade(state: DisputeState) -> Literal["draft", "human"]:
        if state.get("score", 0) >= PASS_SCORE or state.get("attempts", 0) >= MAX_ATTEMPTS:
            return "human"
        return "draft"

    async def human(state: DisputeState) -> dict[str, Any]:
        # Derived from the case, not Python's per-process hash(): this node re-runs on resume, possibly in a new
        # process, and the reviewer's id and the reply's idempotency key must not change.
        case = canonical_json([state["email"]["sender"], state["email"]["subject"], state["email"]["body"]])
        review_id = state.get("review_id") or f"REV-{hashlib.sha256(case.encode()).hexdigest()[:6].upper()}"
        decision = interrupt(
            {
                "kind": "review",
                "review_id": review_id,
                "draft": state.get("draft"),
                "score": state.get("score"),
                "attempts": state.get("attempts"),
                "to": state["email"]["sender"],
                "call": reply_call(state["email"], state.get("draft", ""), review_id),
            }
        )
        return {"decision": decision, "review_id": review_id}

    def after_review(state: DisputeState) -> Literal["send_reply", "close"]:
        return "send_reply" if (state.get("decision") or {}).get("decision") == "approved" else "close"

    async def send_reply(state: DisputeState) -> dict[str, Any]:
        call = reply_call(state["email"], state.get("draft", ""), state.get("review_id", ""))
        reference = await deps.replies.send(
            key=call["step"], approval_token=approval_token(state.get("decision")), **call["input"]
        )
        return {"sent": reference, "status": "replied"}

    async def close(state: DisputeState) -> dict[str, Any]:
        return {"status": "closed"}

    g = StateGraph(DisputeState)
    for name, fn in [
        ("classify", classify),
        ("collect", collect),
        ("draft", draft),
        ("grade", grade),
        ("human", human),
        ("send_reply", send_reply),
        ("close", close),
    ]:
        g.add_node(name, fn)
    g.add_node("extract", extract)  # pyright: ignore[reportArgumentType] - Send carries its own input type
    g.add_edge(START, "classify")
    g.add_conditional_edges("classify", fan_out, ["extract", "collect"])
    g.add_edge("extract", "collect")
    g.add_edge("collect", "draft")
    g.add_edge("draft", "grade")
    g.add_conditional_edges("grade", after_grade, ["draft", "human"])
    g.add_conditional_edges("human", after_review, ["send_reply", "close"])
    g.add_edge("send_reply", END)
    g.add_edge("close", END)
    return g.compile(checkpointer=checkpointer, name="complex_workflow")
