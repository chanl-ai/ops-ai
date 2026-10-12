"""Counts workflow model calls per thread and node in the log, so the cost of re-running a crashed node can be
measured across processes (E2): each call logs `model_call thread=<id> node=<node> kind=<call>`."""

from __future__ import annotations

from langgraph.config import get_config

from ops_agents.graphs.models import Facts, Grade, GraphModels
from ops_service_kit.logging import get_logger

log = get_logger("ops_agents.api.metering")


def _where() -> tuple[str, str]:
    try:
        cfg = get_config()
    except RuntimeError:
        return "-", "-"
    return str(cfg.get("configurable", {}).get("thread_id", "-")), str(
        cfg.get("metadata", {}).get("langgraph_node", "-")
    )


class CountingModels:
    def __init__(self, inner: GraphModels) -> None:
        self._inner = inner

    def _log(self, kind: str) -> None:
        thread, node = _where()
        log.info("model_call", thread=thread, node=node, kind=kind)

    async def classify(self, text: str, labels: list[str]) -> str:
        self._log("classify")
        return await self._inner.classify(text, labels)

    async def extract(self, category: str, name: str, text: str) -> Facts:
        self._log("extract")
        return await self._inner.extract(category, name, text)

    async def draft(self, email: str, evidence: str, feedback: str | None) -> str:
        self._log("draft")
        return await self._inner.draft(email, evidence, feedback)

    async def grade(self, email: str, draft: str) -> Grade:
        self._log("grade")
        return await self._inner.grade(email, draft)
