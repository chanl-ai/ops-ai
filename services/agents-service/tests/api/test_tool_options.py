"""GET /v1/tools/options, the agent page's tools picker (c-135), by failure mode: an operation past the first hundred
not findable; the cursor repeating or skipping one; stored grants not resolving to their names; the whole catalogue
sent to the browser instead of one page; another team's workflow offered."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.activities.tool_directory import OperationRef
from ops_agents.api.routers import tool_catalog
from tests.engine.test_lifecycle_rights import BUILDER, stack  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture

from .test_agent_limits import _app, _data  # pyright: ignore[reportPrivateUsage]


class ManyOperations:
    """A tools-service directory with 130 grantable operations."""

    async def operations(self) -> list[OperationRef]:
        return [
            OperationRef(
                name=f"op_{i:03d}",
                description=f"Operation {i}",
                access="read",
                input_schema={"type": "object"},
                requires_approval=False,
                module_id="mod_bank",
                module_name="Core banking",
            )
            for i in range(130)
        ]


async def test_options_search_page_and_resolve(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, app):
        app.state.runtime.tool_directory = ManyOperations()
        found = _data(await c.get("/v1/tools/options", params={"search": "op_123"}))
        assert [o["id"] for o in found["data"]] == ["op_123"] and found["data"][0]["hint"] == "Core banking"

        first = _data(await c.get("/v1/tools/options", params={"search": "op_", "limit": 70}))
        assert len(first["data"]) == 70 and first["nextCursor"] == "70"
        rest = _data(await c.get("/v1/tools/options", params={"search": "op_", "limit": 70, "cursor": "70"}))
        assert [o["id"] for o in first["data"] + rest["data"]] == [f"op_{i:03d}" for i in range(130)]
        assert rest["nextCursor"] is None

        named = _data(await c.get("/v1/tools/options", params={"ids": ["op_129", "op_gone"]}))
        assert [o["label"] for o in named["data"]] == ["op_129"], "a grant no longer offered is left out"


async def test_another_teams_workflow_is_not_offered(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, _ = stack
    flows = [
        {"id": "ops_refunds", "name": "Refunds", "team_id": "team_ops"},
        {"id": "lending_review", "name": "Loan review", "team_id": "team_lending"},
    ]

    async def published(_rt: Any) -> list[dict[str, Any]]:
        return flows

    async def known(_rt: Any) -> list[dict[str, Any]]:
        return [
            {"id": f"workflow:{w['id']}", "name": w["name"], "server": "Workflows", "description": ""} for w in flows
        ]

    monkeypatch.setattr(tool_catalog, "published_workflows", published)
    monkeypatch.setattr(tool_catalog, "known_tools", known)
    r = await c.get("/v1/tools/options", params={"search": ""}, headers=BUILDER)
    assert r.status_code == 200, r.text
    assert [o["id"] for o in r.json()["data"]["data"]] == ["workflow:ops_refunds"]
