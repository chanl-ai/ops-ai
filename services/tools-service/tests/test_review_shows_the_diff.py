"""A tool module review carries what it approves (c-204), by failure mode: a review that names no operation, host or
secret, so the reviewer approves on a one-line note; and a diff read later than the request, so it can change after it
was asked for. Driven through the real routes into the real `Reviews` client; agents-service is recorded."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_service_kit.settings import Settings
from ops_tools.modules.reviews import Reviews
from ops_tools.modules.seed import load
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, response_checker
from .service_clients import fake_service
from .test_review_decisions import HOST, introspect, jwks, person

SENT: list[dict[str, Any]] = []


async def _agents(request: httpx.Request) -> httpx.Response:
    SENT.append(json.loads(request.content))
    return httpx.Response(201, json={"success": True, "data": {"id": f"pr_{len(SENT)}"}})


@pytest.fixture
async def tools(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, str]]]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    settings = Settings()
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes),
    )
    app = build_app(engine, seed, tenant, auth=auth, reviews=Reviews(fake_service(_agents, "agents")))
    james = person(tenant, "James Richardson", {"team_platform": "builder"})
    sam = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://tools",
        event_hooks={"response": [response_checker(app)]},
    ) as c:
        assert (await c.post("/v1/egress/hosts", json={"value": HOST}, headers=sam)).status_code in (200, 201)
        yield c, james


async def test_a_review_names_the_operations_host_and_secret_it_approves(
    tools: tuple[httpx.AsyncClient, dict[str, str]],
) -> None:
    c, james = tools
    SENT.clear()
    made = await c.post(
        "/v1/tool-modules/blank",
        json={"displayName": "Statements", "name": "c204-statements", "type": "http"},
        headers=james,
    )
    mid = made.json()["data"]["id"]
    op = {
        "name": "get_statement",
        "description": "",
        "access": "read",
        "method": "GET",
        "url": f"https://{HOST}/v1/statements",
        "headers": [{"key": "X-Api-Key", "value": "{{STATEMENTS_KEY}}"}],
    }
    assert (await c.post(f"/v1/tool-modules/{mid}/operations", json=op, headers=james)).status_code == 200
    asked = await c.post(f"/v1/tool-modules/{mid}/reviews", json={"note": "c-204"}, headers=james)
    assert asked.status_code == 200, asked.text
    diff = SENT[-1]["diff"]
    assert [(o["name"], o["method"], o["access"]) for o in diff["added"]] == [("get_statement", "GET", "read")]
    assert diff["hostsAdded"] == [HOST] and diff["secrets"] == ["STATEMENTS_KEY"]
    assert diff["removed"] == [] and diff["changed"] == []
