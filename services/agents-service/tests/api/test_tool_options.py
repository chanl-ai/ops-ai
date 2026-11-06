"""GET /v1/tools/options, the agent page's tools picker, by failure mode: an operation past the first hundred
not findable; the cursor repeating or skipping one; stored grants not resolving to their names; the whole catalogue
sent to the browser instead of one page; another team's workflow offered; the picker silent about an app's tools the
team has not added, or failing when the tools service cannot say."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.activities.tool_directory import OperationRef, ToolsUnavailable
from ops_agents.api.routers import tool_catalog
from tests.engine.test_lifecycle_rights import (  # noqa: F401  # a fixture
    BUILDER,  # pyright: ignore[reportUnusedImport]
    stack,  # pyright: ignore[reportUnusedImport]
)

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

    async def known(_rt: Any, *, fresh: bool = False) -> list[dict[str, Any]]:
        return [
            {"id": f"workflow:{w['id']}", "name": w["name"], "server": "Workflows", "description": ""} for w in flows
        ]

    monkeypatch.setattr(tool_catalog, "published_workflows", published)
    monkeypatch.setattr(tool_catalog, "known_tools", known)
    r = await c.get("/v1/tools/options", params={"search": ""}, headers=BUILDER)
    assert r.status_code == 200, r.text
    assert [o["id"] for o in r.json()["data"]["data"]] == ["workflow:ops_refunds"]


class Cards:
    """tools-service's app cards: Salesforce with 3 of its 15 tools not added, GitHub with all added, a custom app with
    no catalog."""

    down = False

    async def cards(self, person: str | None, team: str | None) -> list[dict[str, Any]]:
        if self.down:
            raise ToolsUnavailable("down")
        return [
            {"id": "plugin:opsai.salesforce", "name": "Salesforce", "toolsCount": 15, "toolsAdded": 12},
            {"id": "plugin:opsai.github", "name": "GitHub", "toolsCount": 3, "toolsAdded": 3},
            {"id": "con_desk", "name": "Ticket desk", "toolsCount": 2, "toolsAdded": None},
        ]


async def test_the_picker_says_how_many_of_an_apps_tools_are_not_added(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, app):
        cards = Cards()
        app.state.runtime.tool_directory, app.state.runtime.app_states = ManyOperations(), cards
        first = _data(await c.get("/v1/tools/options", params={"search": "", "limit": 70}))
        assert first["notAdded"] == [{"appId": "plugin:opsai.salesforce", "name": "Salesforce", "count": 3}]
        assert _data(await c.get("/v1/tools/options", params={"search": "sales"}))["notAdded"][0]["count"] == 3
        assert _data(await c.get("/v1/tools/options", params={"search": "git"}))["notAdded"] == []
        later = _data(await c.get("/v1/tools/options", params={"search": "", "limit": 70, "cursor": "70"}))
        assert later["notAdded"] == [], "said once, above the first page"
        assert _data(await c.get("/v1/tools/options", params={"ids": ["op_001"]}))["notAdded"] == []
        cards.down = True
        down = _data(await c.get("/v1/tools/options", params={"search": "op_001"}))
        assert [o["id"] for o in down["data"]] == ["op_001"] and down["notAdded"] == []
