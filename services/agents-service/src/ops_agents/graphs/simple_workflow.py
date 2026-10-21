# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# langgraph.graph ships without complete type information (no stubs; StateGraph.add_node is partially Unknown).
"""Workflow "Reply to a product question": classify, then answer from the knowledge bases with citations. No pause."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ops_agent_kernel.types import AgentSettings, PromptFragment, TurnRequest
from ops_service_kit.ids import new_id

from .common import GraphDeps, kernel_turn

LABELS = ["product_question", "account_specific", "other"]
ANSWER = PromptFragment(
    "You answer Harbor & Pine Bank customers' product questions for the support team. Answer from the knowledge"
    " provided and cite it; if it does not cover the question, say so. Two to four sentences."
)


class ProductQuestionState(TypedDict):
    question: str
    kb_ids: NotRequired[list[str]]
    category: NotRequired[str]
    answer: NotRequired[str]
    citations: NotRequired[list[dict[str, Any]]]
    no_answer: NotRequired[bool]


def build(deps: GraphDeps, checkpointer: BaseCheckpointSaver[Any] | None) -> CompiledStateGraph[Any, Any, Any, Any]:
    async def classify(state: ProductQuestionState) -> dict[str, Any]:
        return {"category": await deps.models.classify(state["question"], LABELS)}

    async def answer(state: ProductQuestionState) -> dict[str, Any]:
        settings = AgentSettings("wf_product_question", 1, [ANSWER], deps.model_alias, max_tool_calls=0)
        kb_ids = state.get("kb_ids") or [k.id for k in deps.catalog.knowledge_bases]
        req = TurnRequest(new_id("turn"), new_id("run"), settings, [], user_turn=state["question"], kb_ids=kb_ids)
        result = await kernel_turn("answer", req, deps.ports, deps.meter, deps.model_alias)
        citations = [
            {"n": c.n, "documentId": c.passage.document_id, "title": c.passage.title, "section": c.passage.section}
            for c in result.citations
        ]
        return {"answer": result.text, "citations": citations, "no_answer": result.no_answer}

    g = StateGraph(ProductQuestionState)
    g.add_node("classify", classify)
    g.add_node("answer", answer)
    g.add_edge(START, "classify")
    g.add_edge("classify", "answer")
    g.add_edge("answer", END)
    return g.compile(checkpointer=checkpointer, name="simple_workflow")
