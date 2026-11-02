"""The built-in Knowledge bases tool (c-616): `search_knowledge` answers from the calling team's knowledge bases with
the passages and where each came from, through kb-service's own search, called as the run's tenant and team, so another
team's knowledge base is never searched. It runs behind the tool gateway as the platform's local tools do, so grants,
the call log and the team's rules apply as to any tool."""

from __future__ import annotations

from typing import Any, cast

from ops_agent_kernel.ports import ToolOutcome
from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable

# Passages one search hands the model; enough to cite, few enough not to fill its context.
LIMIT = 5


class KnowledgeSearch:
    def __init__(self, kb: ServiceClient) -> None:
        """`kb` calls kb-service as tools-service with `knowledge:view`; each call names the run's tenant and team."""
        self.kb = kb

    async def run(self, arguments: dict[str, Any], *, tenant: str, team: str | None) -> ToolOutcome:
        if not team:
            return ToolOutcome(False, {"error": "A knowledge base belongs to a team; this call acts in none."})
        query = str(arguments.get("query") or "").strip()
        if not query:
            return ToolOutcome(False, {"error": "Say what to search for."})
        try:
            bases = cast(list[dict[str, Any]], await self.kb.get("/v1/knowledge-bases/refs", tenant=tenant, team=team))
            named = [str(c).strip() for c in cast(list[Any], arguments.get("collections") or []) if str(c).strip()]
            # Named by id or by name; none named searches every knowledge base the team has.
            by = {str(b["id"]): str(b["id"]) for b in bases} | {str(b["name"]).lower(): str(b["id"]) for b in bases}
            unknown = [n for n in named if n not in by and n.lower() not in by]
            if unknown:
                return ToolOutcome(False, {"error": f"The team has no knowledge base {', '.join(unknown)}."})
            ids = list(dict.fromkeys(by.get(n) or by[n.lower()] for n in named)) or [str(b["id"]) for b in bases]
            if not ids:
                return ToolOutcome(True, {"passages": [], "note": "The team has no knowledge bases yet."})
            body = {"kbIds": ids, "question": query, "limit": LIMIT}
            found = cast(
                dict[str, Any], await self.kb.post("/v1/knowledge-bases/search", body, tenant=tenant, team=team)
            )
        except (ServiceCallError, ServiceUnreachable) as e:
            # Said plainly, so the agent says knowledge is unavailable instead of answering as if nothing matched.
            return ToolOutcome(False, {"error": f"The knowledge bases cannot be reached: {type(e).__name__}."})
        names = {str(b["id"]): str(b["name"]) for b in bases}
        passages = [
            {
                "text": p["text"],
                "title": p["title"],
                "section": p.get("section"),
                "page": p.get("page"),
                "knowledgeBase": names.get(str(p["kbId"]), str(p["kbId"])),
                "itemId": p["itemId"],
            }
            for p in cast(list[dict[str, Any]], found.get("passages") or [])
        ]
        return ToolOutcome(True, {"passages": passages})
