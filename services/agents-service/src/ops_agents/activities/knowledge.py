"""Knowledge for agents: the knowledge bases a thread may search, and the passages a turn cites.

`KbService` asks kb-service, with a service token holding `knowledge:view` and naming the tenant and team of the request
or run: GET /v1/knowledge-bases/refs for the knowledge bases, POST /v1/knowledge-bases/search for passages. It searches
only the ids it is handed, which are the thread's, already checked against the agent's grants (api/routers/chat.py).
When kb-service cannot answer, the turn says knowledge is unavailable rather than answer uncited.

With no kb-service configured, `NoKnowledgeService` answers every knowledge request as unavailable: a stack set up
without one says so in its replies rather than answering from anywhere else. Tests inject a stand-in through
create_app's `knowledge` (tests/knowledge_fixture.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

from ops_agent_kernel.ports import KnowledgeUnavailableError
from ops_agent_kernel.types import Passage
from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.errors import ApiError
from ops_service_kit.logging import get_logger

from ..store.tenancy import current_tenant

log = get_logger("ops_agents.knowledge")


@dataclass(frozen=True)
class KbRef:
    id: str
    name: str


class KnowledgeBases(Protocol):
    async def bases(self) -> list[KbRef]: ...


class Knowledge(KnowledgeBases, Protocol):
    """Both halves an agents-service needs: the knowledge bases a thread may name, and the passages a turn cites."""

    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Passage]: ...


class KnowledgeUnavailable(ApiError):
    status = 503
    code = "knowledge_unavailable"


class KbService:
    def __init__(self, kb: ServiceClient) -> None:
        """`kb` calls kb-service as this service for the current tenant and team (api/app.py)."""
        self.kb = kb

    async def bases(self) -> list[KbRef]:
        try:
            rows = cast(list[dict[str, Any]], await self.kb.get("/v1/knowledge-bases/refs"))
        except (ServiceCallError, ServiceUnreachable) as e:
            raise KnowledgeUnavailable(
                "The knowledge service cannot be reached, so the knowledge bases are unknown. Try again shortly."
            ) from e
        return [KbRef(str(b["id"]), str(b["name"])) for b in rows]

    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Passage]:
        body = {"kbIds": kb_ids, "question": query, "limit": k}
        try:
            found = cast(dict[str, Any], await self.kb.post("/v1/knowledge-bases/search", body))
        except (ServiceCallError, ServiceUnreachable) as e:
            log.warning("knowledge_unavailable", tenant=current_tenant(), error=type(e).__name__)
            raise KnowledgeUnavailableError("kb-service did not answer") from e
        return [
            Passage(
                document_id=str(p["itemId"]),
                title=str(p["title"]),
                section=str(p["section"]),
                version=str(p["version"]),
                text=str(p["text"]),
                kb_id=str(p["kbId"]),
                page=cast(int | None, p.get("page")),
            )
            for p in cast(list[dict[str, Any]], found["passages"])
        ]


class NoKnowledgeService:
    """No kb-service configured: knowledge bases are unknown (503) and every search is unavailable."""

    async def bases(self) -> list[KbRef]:
        raise KnowledgeUnavailable("No knowledge service is configured for this stack (OPS_KB_URL).")

    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Passage]:
        raise KnowledgeUnavailableError("no knowledge service is configured")
