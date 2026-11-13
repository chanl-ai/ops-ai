"""MCP links, made on `/v1/mcp-links` and driven by the official SDK's client at `/mcp/<team>/<link>`: one test per way
a link could offer or run more than it names, keep answering while paused, lose its calls from its own list, or start a
workflow without the person's right to."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any

import httpx
import httpx2
import pytest
from fastapi import Header, Request
from fastapi.responses import JSONResponse
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import Implementation
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Identity

# pyright: reportPrivateUsage=false
from .test_mcp_platform_tools import (
    GRIDS,
    RUN,
    TEAM,
    Agents,
    People,
    Stack,
    _content,
    _person,
    _scopes,
    _stack,
)

# Who may make and pause links (a team admin's deployments cells) and start a workflow; who may only read them.
GRIDS["linker"] = [
    *RUN,
    ("deployments", "view", "all"),
    ("deployments", "create", "all"),
    ("deployments", "edit", "all"),
    ("workflows", "run", "all"),
    ("activity", "view", "all"),
]
GRIDS["reader"] = [*RUN, ("deployments", "view", "all")]


SCHEMA = {"type": "object", "required": ["claim"], "properties": {"claim": {"type": "string"}}}


class RunAgents(Agents):
    """agents-service with its run start, deciding by the token's scopes as `require_runs_start` does."""

    def __init__(self) -> None:
        super().__init__()
        self.started: list[dict[str, Any]] = []

        @self.app.post("/v1/runs")
        async def start(request: Request) -> Any:  # pyright: ignore[reportUnusedFunction]
            if "workflows:run" not in _scopes(request):
                return JSONResponse({"error": {"code": "role_required", "message": "no workflows:run"}}, 403)
            body = await request.json()
            self.started.append(body)
            started = {"runId": "run_1", "workflowId": body["workflowId"], "version": 3, "status": "queued"}
            return JSONResponse({"data": started}, 202)

        @self.app.get("/v1/tools/{tool_id}")
        async def catalog_row(tool_id: str, request: Request) -> Any:  # pyright: ignore[reportUnusedFunction]
            if "tools:view" not in _scopes(request) or tool_id != "workflow:wf_claims":
                return JSONResponse({"error": {"code": "not_found", "message": tool_id}}, 404)
            return {
                "data": {"id": tool_id, "name": "Claims intake", "description": "Opens a claim.", "inputSchema": SCHEMA}
            }


async def _rest_principal(  # noqa: PLR0917 - FastAPI reads these as the headers Identity.principal takes
    self: People,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
    x_team_id: Annotated[str | None, Header()] = None,
    x_dev_user: Annotated[str | None, Header()] = None,
) -> Any:
    """The same people on the REST routes as at the MCP door: `Bearer ok_<who>` names them; the fixture's own setup
    keeps the dev caller."""
    if not (authorization or "").startswith("Bearer ok_"):
        return await Identity.principal(self, request, authorization, x_api_key, x_team_id, x_dev_user)
    return _person(str(authorization).split()[-1].removeprefix("ok_"), self.tenant)


@pytest.fixture
async def stack(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]], monkeypatch: Any
) -> AsyncIterator[Stack]:
    monkeypatch.setenv("OPS_PLATFORM_PUBLIC_URL", "https://ops.bank.test/api/platform")
    monkeypatch.setenv("OPS_TOOLS_PUBLIC_URL", "https://ops.bank.test/api/tools")
    monkeypatch.setattr(People, "principal", _rest_principal)
    async for s in _stack(
        engine=engine, seed=seed, tenant=tenant, catalog=catalog_tools, monkeypatch=monkeypatch, agents=RunAgents()
    ):
        yield s


def _rest(stack: Stack, who: str) -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer ok_{who}", "X-Team-Id": TEAM}
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=stack.app), base_url="http://tools", headers=headers)


def _session(stack: Stack, who: str, path: str) -> Client:
    http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=stack.app),
        base_url="http://tools",
        headers={"Authorization": f"Bearer ok_{who}"},
    )
    return Client(
        streamable_http_client(f"http://tools{path}", http_client=http),
        client_info=Implementation(name="pytest-assistant", version="1.0"),
        cache=None,
    )


async def _link(stack: Stack, tools: list[dict[str, str]]) -> dict[str, Any]:
    async with _rest(stack, "linker") as rest:
        r = await rest.post("/v1/mcp-links", json={"name": "Claims lookups", "tools": tools})
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def test_a_link_lists_and_runs_only_its_tools_and_lists_its_own_calls(stack: Stack) -> None:
    link = await _link(stack, [{"id": "lookup_case", "label": "Look up a case"}])
    assert link["url"] == f"https://ops.bank.test/api/tools/mcp/{TEAM}/claims-lookups"
    path = f"/mcp/{TEAM}/claims-lookups"
    async with stack.app.router.lifespan_context(stack.app), _session(stack, "linker", path) as c:
        listed = [t.name for t in (await c.list_tools()).tools]
        ran = await c.call_tool("lookup_case", {"caseId": "CASE-4112"})
        other = await c.call_tool("list_templates", {})
    assert listed == ["lookup_case"], "a link offers its picked tools only, no platform tools beside them"
    assert ran.is_error is False, ran
    assert other.is_error is True and _content(other).get("code") == "not_on_link"
    async with _rest(stack, "linker") as rest:
        calls = (await rest.get("/v1/executions", params={"link": link["id"]})).json()["data"]["data"]
        listed_links = (await rest.get("/v1/mcp-links")).json()["data"]
    assert [(x["target"], x["channel"]) for x in calls] == [("lookup_case", "mcp")]
    assert listed_links[0]["lastCall"]["outcome"] == "ok"


async def test_a_paused_link_refuses_and_a_reader_cannot_pause_or_make_one(stack: Stack) -> None:
    link = await _link(stack, [{"id": "lookup_case", "label": "Look up a case"}])
    async with _rest(stack, "reader") as rest:
        refused = await rest.patch(f"/v1/mcp-links/{link['id']}", json={"paused": True})
        made = await rest.post("/v1/mcp-links", json={"name": "Mine", "tools": [{"id": "lookup_case", "label": "x"}]})
    assert (refused.status_code, made.status_code) == (403, 403), (refused.text, made.text)
    async with _rest(stack, "linker") as rest:
        assert (await rest.patch(f"/v1/mcp-links/{link['id']}", json={"paused": True})).status_code == 200
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    async with (
        stack.app.router.lifespan_context(stack.app),
        httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=stack.app),
            base_url="http://tools",
            headers={"Authorization": "Bearer ok_linker"},
        ) as http,
    ):
        r = await http.post(
            f"/mcp/{TEAM}/claims-lookups", json=body, headers={"Accept": "application/json, text/event-stream"}
        )
    assert (r.status_code, r.json()["error"]["code"]) == (503, "link_paused"), r.text


async def test_a_link_takes_only_tools_the_team_can_run(stack: Stack) -> None:
    async with _rest(stack, "linker") as rest:
        r = await rest.post(
            "/v1/mcp-links", json={"name": "Payroll", "tools": [{"id": "run_payroll", "label": "Run payroll"}]}
        )
    assert (r.status_code, r.json()["error"]["code"]) == (422, "tool_not_runnable"), r.text


async def test_a_picked_workflow_starts_its_live_version_only_for_who_may_run_it(stack: Stack) -> None:
    await _link(stack, [{"id": "workflow:wf_claims", "label": "Claims intake"}])
    path = f"/mcp/{TEAM}/claims-lookups"
    async with stack.app.router.lifespan_context(stack.app), _session(stack, "linker", path) as c:
        [listed] = (await c.list_tools()).tools
        assert (listed.name, listed.input_schema, listed.description) == (
            "workflow__wf_claims",
            SCHEMA,
            "Opens a claim.",
        )
        started = await c.call_tool("workflow__wf_claims", {"claim": "4471"})
    async with stack.app.router.lifespan_context(stack.app), _session(stack, "reader", path) as c:
        refused = await c.call_tool("workflow__wf_claims", {"claim": "4471"})
    assert started.is_error is False and _content(started).get("runId") == "run_1", started
    agents: Any = stack.agents
    assert agents.started == [{"workflowId": "wf_claims", "input": {"claim": "4471"}, "mode": "live"}]
    assert refused.is_error is True, "a person without workflows.run starts nothing"
