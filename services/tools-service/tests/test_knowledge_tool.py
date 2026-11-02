"""The built-in Knowledge bases tool, `search_knowledge` (c-616 PV1), by failure mode: it searches another team's
knowledge bases; a knowledge base named by its name is not found; kb-service's outage reaches the agent as a crash or
as no results; and an install does not serve it. kb-service is faked on the two routes the tool calls."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from ops_identity import ServiceClient, dev_service_signer
from ops_tools.knowledge_tools import KnowledgeSearch
from ops_tools.registry import ToolRegistry

TENANT, OPS, RETAIL = "t_bank", "team_ops", "team_retail"
BASES = {OPS: [{"id": "kb_policies", "name": "Card policies"}], RETAIL: [{"id": "kb_retail", "name": "Retail"}]}


def _team(request: httpx.Request) -> str:
    body = request.headers["Authorization"].removeprefix("Bearer ").split(".")[1]
    return str(json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))["team_id"])


@dataclass
class FakeKb:
    down: bool = False
    asked: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            return httpx.Response(503, json={"success": False, "error": {"code": "unavailable", "message": "down"}})
        team = _team(request)
        if request.url.path == "/v1/knowledge-bases/refs":
            return httpx.Response(200, json={"success": True, "data": BASES.get(team, [])})
        body = json.loads(request.content)
        self.asked.append({"team": team, **body})
        owned = {b["id"] for b in BASES.get(team, [])}
        found = {"itemId": "doc_1", "title": "Chargeback rules", "section": "4.2", "version": "3", "page": 2}
        passages = [{**found, "text": "File within 120 days.", "kbId": k} for k in body["kbIds"] if k in owned]
        return httpx.Response(200, json={"success": True, "data": {"passages": passages}})

    def tool(self) -> KnowledgeSearch:
        http = httpx.AsyncClient(transport=httpx.MockTransport(self.handle), base_url="http://kb")
        return KnowledgeSearch(ServiceClient(http, dev_service_signer(), "tools", "kb", ["knowledge:view"]))


async def test_a_search_reads_only_the_calling_teams_knowledge_bases() -> None:
    kb = FakeKb()
    out = await kb.tool().run({"query": "How long to file a chargeback?"}, tenant=TENANT, team=OPS)
    assert out.ok, out.output
    assert [p["text"] for p in out.output["passages"]] == ["File within 120 days."]
    assert kb.asked == [
        {"team": OPS, "kbIds": ["kb_policies"], "question": "How long to file a chargeback?", "limit": 5}
    ]


async def test_a_knowledge_base_is_named_by_its_name_and_another_teams_is_not_found() -> None:
    kb = FakeKb()
    named = await kb.tool().run({"query": "q", "collections": ["Card policies"]}, tenant=TENANT, team=OPS)
    assert named.ok and kb.asked[-1]["kbIds"] == ["kb_policies"], named.output
    other = await kb.tool().run({"query": "q", "collections": ["Retail"]}, tenant=TENANT, team=OPS)
    assert not other.ok and "Retail" in str(other.output), other.output


async def test_kb_services_outage_is_a_tool_error_not_no_results() -> None:
    out = await FakeKb(down=True).tool().run({"query": "q"}, tenant=TENANT, team=OPS)
    assert not out.ok and "cannot be reached" in str(out.output["error"]), out.output


async def test_every_install_serves_it(local_catalog: Any, store: Any, tenant: str) -> None:
    resolved = await ToolRegistry(local_catalog, store).resolve("search_knowledge", tenant_id=tenant, team_id=OPS)
    assert resolved is not None and resolved.access == "read" and resolved.executor == "local", resolved
