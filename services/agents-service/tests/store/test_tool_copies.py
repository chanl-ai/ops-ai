"""The tool catalogue copy on the migrated test database, by failure mode: one tenant or team sees another's modules or
grants through the store read (a module keyed by id alone, a grant read without its team, an ended grant still
shown); the resync stops at its first page, misses a tenant after one fails, or drops a seed row at revision 0."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api.app import required_client
from ops_agents.api.tool_catalog_copy import keep_in_step, resync_all
from ops_agents.store.background import heartbeats
from ops_agents.store.tenancy import tenant_scope
from ops_agents.store.tool_copies import RESYNC_KEY, ToolCopies
from ops_identity.client import ServiceCallError, ServiceUnreachable
from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.outbox import Event, ToolOperation, ToolPublished, ToolTeamStateChanged
from ops_store.testing import loop_reports_failure


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


def module(tenant: str, mid: str, owner: str | None, ops: list[str], *, rev: int = 1, name: str = "") -> Event:
    payload = ToolPublished(
        id=mid,
        name=name or mid,
        owner_team=owner,
        operations=[ToolOperation(id=f"{mid}.{o}", name=o, access="read") for o in ops],
    )
    # The resync names a workspace-level module with no team, as tools-service does.
    return Event(name=payload.kind, tenant_id=tenant, team_id=owner, revision=rev, payload=payload)


def grant(tenant: str, team: str, mid: str, ops: list[str], *, expires: str | None = None) -> Event:
    payload = ToolTeamStateChanged(
        id=f"approval:{mid}", module_id=mid, via="approval", operations=ops, expires_at=expires
    )
    return Event(name=payload.kind, tenant_id=tenant, team_id=team, revision=1, payload=payload)


async def seen(engine: AsyncEngine, tenant: str, team: str) -> list[str]:
    """What a request of `team` lists: under its own team scope, as the request's caller sets it."""
    with isolation.scope(tenant, team):
        return [f"{t.module_id}/{t.name}" for t in await ToolCopies(engine).visible(team)]


async def test_two_tenants_and_two_teams_never_see_each_others_rows(engine: AsyncEngine) -> None:
    a, b = f"a-{uuid4().hex[:8]}", f"b-{uuid4().hex[:8]}"
    with tenant_scope(a):
        await ToolCopies(engine).apply(
            [
                module(a, "m_own", "team_x", ["read_x"]),
                module(a, "m_all", None, ["read_all"]),
                module(a, "m_y", "team_y", ["read_b", "write_c"]),
                module(a, "m_ended", "team_y", ["read_d"]),
                grant(a, "team_x", "m_y", ["read_b"]),
                grant(a, "team_x", "m_ended", ["read_d"], expires="2000-01-01T00:00:00+00:00"),
            ]
        )
    with tenant_scope(b):
        # The same module id and team id in another tenant are another tenant's rows.
        await ToolCopies(engine).apply([module(b, "m_own", "team_x", ["read_z"]), grant(b, "team_x", "m_y", ["x"])])
    cases: list[tuple[str, str, list[str]]] = [
        (a, "team_x", ["m_all/read_all", "m_y/read_b", "m_own/read_x"]),
        (a, "team_y", ["m_all/read_all", "m_y/read_b", "m_ended/read_d", "m_y/write_c"]),
        (b, "team_x", ["m_own/read_z"]),
        (b, "team_y", []),
    ]
    for tenant, team, want in cases:
        assert await seen(engine, tenant, team) == want, (tenant, team)


def _tenant_of(request: httpx.Request) -> tuple[str, list[str]]:
    """The tenant and scopes the service token names, read as tools-service's verifier would before it checks them."""
    token = request.headers["Authorization"].removeprefix("Bearer ").split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
    return str(claims["tenant_id"]), list(claims["scopes"])


async def test_the_resync_pages_every_tenant_and_reports_a_failed_one(engine: AsyncEngine) -> None:
    a, b, down = (f"{p}-{uuid4().hex[:8]}" for p in ("a", "b", "c"))
    catalogue: dict[str, list[list[dict[str, Any]]]] = {
        # Three pages of one module each, the first a seed row at revision 0 and workspace-level.
        a: [
            [module(a, "m1", None, ["one"], rev=0).model_dump(by_alias=True, mode="json")],
            [module(a, "m2", "team_x", ["two"]).model_dump(by_alias=True, mode="json")],
            [
                module(a, "m3", "team_y", ["three"]).model_dump(by_alias=True, mode="json"),
                grant(a, "team_x", "m3", ["three"]).model_dump(by_alias=True, mode="json"),
            ],
        ],
        b: [[module(b, "m1", "team_x", ["b_one"]).model_dump(by_alias=True, mode="json")]],
    }
    asked: list[tuple[str, str | None]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        tenant, scopes = _tenant_of(request)
        assert request.url.path == "/v1/tool-catalog" and "tools:view" in scopes
        after = request.url.params.get("after")
        asked.append((tenant, after))
        if tenant == down:
            return httpx.Response(503, json={"error": {"code": "unavailable", "message": "down"}})
        pages = catalogue[tenant]
        n = 0 if after is None else int(after.removeprefix("p")) + 1
        more = n + 1 < len(pages)
        return httpx.Response(200, json={"data": {"items": pages[n], "nextCursor": f"p{n}" if more else None}})

    http = httpx.AsyncClient(base_url="http://tools", transport=httpx.MockTransport(answer))
    tools = required_client(Settings(), http, "tools")

    async def tenants() -> list[str]:
        return [down, b, a]

    with pytest.raises((ServiceCallError, ServiceUnreachable)):
        await resync_all(engine, tools, tenants, page=1)
    # Every page of each tenant was asked, the failed tenant's did not stop the one after it.
    assert asked == [(a, None), (a, "p0"), (a, "p1"), (b, None), (down, None)]
    assert await seen(engine, a, "team_x") == ["m1/one", "m3/three", "m2/two"]
    assert await seen(engine, b, "team_x") == ["m1/b_one"]


async def test_a_failed_resync_pass_shows_on_health(client: AsyncClient, database_url: str) -> None:
    class Down:
        async def get(self, path: str, **kw: Any) -> Any:
            raise ServiceUnreachable("tools-service is down")

    engine, stop, running = create_async_engine(database_url), asyncio.Event(), list[asyncio.Task[None]]()

    async def tenants() -> list[str]:
        return [f"a-{uuid4().hex[:8]}"]

    def trip() -> None:
        loop = keep_in_step(engine, Down(), stop=stop, beats=heartbeats(engine), tenants=tenants)
        running.append(asyncio.create_task(loop))

    try:
        await loop_reports_failure(client, RESYNC_KEY, trip, within_s=10)
    finally:
        stop.set()
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        await engine.dispose()
