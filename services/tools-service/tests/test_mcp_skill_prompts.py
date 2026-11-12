"""Skills as MCP prompts after agents-service owns rendering. Failure modes: a draft or retired skill listed (the list
must ask for the published view); a part of one skill not offered as its own prompt; prompts/get filling text itself
instead of calling render, so a required argument left empty is served as {{name}}."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncEngine

from .test_mcp_platform_tools import Stack, _stack  # pyright: ignore[reportPrivateUsage]

CLIENT: list[dict[str, Any]] = [{"name": "client", "description": "The client", "required": True}]


class PartsAgents:
    """agents-service with one published skill with two parts: it lists only under view=published and renders."""

    def __init__(self) -> None:
        self.app = FastAPI()
        self.made: list[str] = []
        self.rendered: list[dict[str, Any]] = []
        row: dict[str, Any] = {
            "id": "sk_sales",
            "slug": "sales",
            "name": "Sales",
            "useWhen": "",
            "inputs": [],
            "parts": [
                {"slug": "prepare-meeting", "name": "Prepare a meeting", "useWhen": "Before", "inputs": CLIENT},
                {"slug": "update-opportunity", "name": "Update an opportunity", "useWhen": "After", "inputs": []},
            ],
        }

        @self.app.get("/v1/skills")
        async def skills_page(request: Request) -> Any:  # pyright: ignore[reportUnusedFunction]
            rows: list[dict[str, Any]] = (
                [row] if request.query_params.get("view") == "published" else [row, {**row, "slug": "draft"}]
            )
            return {"data": {"data": rows, "total": len(rows)}}

        @self.app.post("/v1/skills/{skill_id}/render")
        async def render(skill_id: str, request: Request) -> Any:  # pyright: ignore[reportUnusedFunction]
            body = await request.json()
            self.rendered.append({"skillId": skill_id, **body})
            if not body["inputs"].get("client"):
                return JSONResponse({"error": {"code": "missing_input", "message": "client is required."}}, 422)
            return {"data": {"text": f"Brief me on {body['inputs']['client']}."}}


@pytest.fixture
async def parts(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]], monkeypatch: Any
) -> AsyncIterator[Stack]:
    async for s in _stack(
        engine=engine,
        seed=seed,
        tenant=tenant,
        catalog=catalog_tools,
        monkeypatch=monkeypatch,
        agents=PartsAgents(),  # pyright: ignore[reportArgumentType]
    ):
        yield s


async def test_each_published_part_is_a_prompt_and_get_is_rendered_by_agents_service(parts: Stack) -> None:
    agents: Any = parts.agents
    async with parts.app.router.lifespan_context(parts.app), parts.session("runner") as c:
        listed = {p.name: p for p in (await c.list_prompts()).prompts}
        got = await c.get_prompt("sales-prepare-meeting", {"client": "Okafor"})
        with pytest.raises(Exception, match="client is required"):
            await c.get_prompt("sales-prepare-meeting", {})
    assert sorted(listed) == ["sales-prepare-meeting", "sales-update-opportunity"], listed
    arguments: list[Any] = list(listed["sales-prepare-meeting"].arguments or [])
    assert [(a.name, a.required) for a in arguments] == [("client", True)]
    assert "Okafor" in str(got.messages[0].content)
    assert agents.rendered[0] == {"skillId": "sk_sales", "part": "prepare-meeting", "inputs": {"client": "Okafor"}}
