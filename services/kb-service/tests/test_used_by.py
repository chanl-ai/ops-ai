"""A knowledge base's "used by", by failure mode: the list or detail naming no agent while agents cite it,
and an unreachable agents-service read as "no agent uses it", which would let a base in use be deleted without the
console's typed confirmation."""

from __future__ import annotations

import asyncio
import base64
import json
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import ServiceClient, dev_service_signer
from ops_kb.agents import AgentsUsage, StaticAgents
from ops_kb.app import agents_usage
from ops_service_kit.settings import Settings

from .conftest import kb_client
from .test_bases_and_sources import POLICIES, data


def agents_client(handler: Any) -> ServiceClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://agents")
    return ServiceClient(http, dev_service_signer(), "kb", "agents", ["agents:view"])


async def test_the_list_and_the_detail_name_the_agents_that_cite_a_base(engine: AsyncEngine, tenant: str) -> None:
    async with kb_client(engine, tenant) as setup:
        kb = data(await setup.post("/v1/knowledge-bases", json=POLICIES), 201)
    agents = StaticAgents({kb["id"]: ["Branch Policy", "Advisor's Helper"], "kb_other": ["Someone else"]})
    async with kb_client(engine, tenant, agents=agents) as c:
        listed = data(await c.get("/v1/knowledge-bases"))["data"]
        detail = data(await c.get(f"/v1/knowledge-bases/{kb['id']}"))
    assert next(r for r in listed if r["id"] == kb["id"])["agentNames"] == ["Branch Policy", "Advisor's Helper"]
    assert detail["agentNames"] == ["Branch Policy", "Advisor's Helper"]


async def test_an_unreachable_agents_service_marks_used_by_unknown_without_failing_the_list(
    engine: AsyncEngine, tenant: str
) -> None:
    """The pages still load; `agentsKnown` false keeps the console's delete confirmation strict."""
    async with kb_client(engine, tenant) as setup:
        kb = data(await setup.post("/v1/knowledge-bases", json=POLICIES), 201)

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    agents = AgentsUsage(agents_client(down))
    async with kb_client(engine, tenant, agents=agents) as c:
        detail = data(await c.get(f"/v1/knowledge-bases/{kb['id']}"))
        listed = data(await c.get("/v1/knowledge-bases"))["data"]
    assert (detail["agentNames"], detail["agentsKnown"]) == ([], False)
    assert next(r for r in listed if r["id"] == kb["id"])["agentsKnown"] is False


async def test_agents_of_other_teams_are_counted_not_named(engine: AsyncEngine, tenant: str) -> None:
    async with kb_client(engine, tenant) as setup:
        kb = data(await setup.post("/v1/knowledge-bases", json=POLICIES), 201)
    seen: list[str | None] = []
    asked: list[list[str]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        token = request.headers["Authorization"].removeprefix("Bearer ")
        seen.append(json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))["team_id"])
        asked.append(request.url.params.get_list("ids"))
        row = {"kbId": kb["id"], "agents": [{"id": "ag_1", "name": "Branch Policy"}], "elsewhere": 2}
        return httpx.Response(200, json={"success": True, "data": [row]})

    # The team is signed into the token, never sent as a query parameter.
    agents = AgentsUsage(agents_client(answer))
    async with kb_client(engine, tenant, agents=agents) as c:
        detail = data(await c.get(f"/v1/knowledge-bases/{kb['id']}"))
    assert (detail["agentNames"], detail["agentsElsewhere"], detail["agentsKnown"]) == (["Branch Policy"], 2, True)
    assert seen and seen[0], "kb-service names the caller's team in its token"
    # Only the bases kb-service shows are asked about, so agents-service reads no other base's agents.
    assert asked == [[kb["id"]]], asked


async def test_a_slow_agents_service_is_asked_once_within_its_short_wait(
    engine: AsyncEngine, tenant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """agents-service accepting the connection and never answering: the list asks once, waits the "used by" timeout
    and answers without usage, well inside the console's own wait, instead of three tries of the endpoint's 10 s."""
    asked = 0

    async def hold(_r: asyncio.StreamReader, _w: asyncio.StreamWriter) -> None:
        nonlocal asked
        asked += 1
        await asyncio.sleep(60)

    server = await asyncio.start_server(hold, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setenv("OPS_AGENTS_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setenv("OPS_KB_USED_BY_TIMEOUT_S", "0.3")
    async with kb_client(engine, tenant) as setup:
        kb = data(await setup.post("/v1/knowledge-bases", json=POLICIES), 201)
    try:
        async with kb_client(engine, tenant, agents=agents_usage(Settings())) as c:
            listed = data(await asyncio.wait_for(c.get("/v1/knowledge-bases"), 5))["data"]
    finally:
        server.close()
    assert next(r for r in listed if r["id"] == kb["id"])["agentsKnown"] is False
    assert asked == 1
