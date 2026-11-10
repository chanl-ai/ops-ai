"""Two optional steps around a search, both off by default and both called through models-service on the base's
chat-model alias with kb-service's own key (`ops_service_kit.model_calls`, step `kb:query`): rewriting the question
with the base's instruction before the lanes run, and reranking the best fused pieces, each scored 0 to 10.

A step that fails (no models-service, a refusal, an answer that cannot be read) leaves the search as it would have
been and says why, so a search never fails because a model did."""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any, Protocol, cast

from ops_service_kit.model_calls import ModelCallError, ModelCalls

QUERY_STEP = "kb:query"
# How many fused pieces a rerank scores; the base's limit is then taken from the reranked order.
RERANK_POOL = 20
# A piece's text sent to the reranker is cut to this many characters, so twenty pieces stay one modest call.
RERANK_CHARS = 1200
REWRITE_MODES = ("off", "rewrite")

REWRITE_SYSTEM = (
    "You rewrite a person's question into a search query for a knowledge base. Follow the knowledge base's "
    "instruction. Keep every fact the question states; add none it does not. Answer with the rewritten question only."
)
RERANK_SYSTEM = (
    "You score how well each numbered passage answers the question, from 0 (does not answer it) to 10 (answers it "
    "fully). Score every passage once, by its number."
)
REWRITE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"question": {"type": "string"}},
    "required": ["question"],
}
RERANK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"n": {"type": "integer"}, "score": {"type": "number"}},
                "required": ["n", "score"],
            },
        }
    },
    "required": ["scores"],
}


class QueryStepFailed(Exception):
    """A rewrite or rerank that gave nothing usable; `reason` is said on the search's answer."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class QueryModel(Protocol):
    async def rewrite(self, question: str, instruction: str, *, alias: str, tenant: str) -> str: ...

    async def scores(self, question: str, pieces: list[str], *, alias: str, tenant: str) -> list[float]:
        """One score from 0 to 10 per piece, in the pieces' order."""
        ...


@dataclass
class ModelsQuery:
    """QueryModel on models-service through the one model client."""

    calls: ModelCalls

    async def _ask(self, system: str, user: str, schema: dict[str, Any], *, alias: str, tenant: str) -> Any:
        try:
            return await replace(self.calls, alias=alias).structured(
                system, user, schema, tenant=tenant, step=QUERY_STEP
            )
        except ModelCallError as e:
            raise QueryStepFailed(f"model_unavailable: {e.code}") from e

    async def rewrite(self, question: str, instruction: str, *, alias: str, tenant: str) -> str:
        user = f"Instruction: {instruction or 'Make the question a clear search query.'}\n\nQuestion: {question}"
        answer = await self._ask(REWRITE_SYSTEM, user, REWRITE_SCHEMA, alias=alias, tenant=tenant)
        rewritten = str(cast(dict[str, Any], answer).get("question") or "").strip() if isinstance(answer, dict) else ""
        if not rewritten:
            raise QueryStepFailed("unreadable_answer")
        return rewritten

    async def scores(self, question: str, pieces: list[str], *, alias: str, tenant: str) -> list[float]:
        numbered = "\n\n".join(f"[{n}] {p[:RERANK_CHARS]}" for n, p in enumerate(pieces, start=1))
        user = f"Question: {question}\n\nPassages:\n{numbered}"
        answer = await self._ask(RERANK_SYSTEM, user, RERANK_SCHEMA, alias=alias, tenant=tenant)
        rows = cast(list[Any], cast(dict[str, Any], answer).get("scores") or []) if isinstance(answer, dict) else []
        by_n: dict[int, float] = {}
        for r in rows:
            if isinstance(r, dict):
                row = cast(dict[str, Any], r)
                try:
                    by_n[int(row["n"])] = max(0.0, min(10.0, float(row["score"])))
                except (KeyError, TypeError, ValueError):
                    continue
        if not by_n:
            raise QueryStepFailed("unreadable_answer")
        # A piece the model left out scores 0, so it falls below every piece it scored.
        return [by_n.get(n, 0.0) for n in range(1, len(pieces) + 1)]


@dataclass(frozen=True)
class QuerySteps:
    """What the bases ask of the two steps, each on the alias of the first base that asks for it (in the order the
    caller named the bases): rerank when any base asks, and the rewrite instruction of the first base rewriting."""

    rerank_alias: str | None = None
    rewrite_alias: str | None = None
    instruction: str = ""


def steps_for(settings: list[dict[str, Any]], default_alias: str) -> QuerySteps:
    reranking = [r for r in settings if r.get("rerank")]
    rewriting = [r for r in settings if r.get("rewrite") == "rewrite"]

    def alias(r: dict[str, Any]) -> str:
        return str(r.get("queryModel") or default_alias)

    return QuerySteps(
        rerank_alias=alias(reranking[0]) if reranking else None,
        rewrite_alias=alias(rewriting[0]) if rewriting else None,
        instruction=str(rewriting[0].get("rewriteInstructions") or "") if rewriting else "",
    )


def ms_since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
