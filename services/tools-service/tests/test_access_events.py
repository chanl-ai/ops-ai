"""A workflow's request for a module's operations is reported as a service event (c-257), by failure mode: the request
saved with no event, so no run ever asks anyone; an event for the wrong team or with no asker, so the wrong people
decide or the requester rule has nobody to refuse; an event left behind by a request that was refused; and the relay
sending it somewhere agents-service does not read it."""

from __future__ import annotations

import json
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.store.event_relay import sender
from ops_tools.store.modules import module_operations, service_outbox, tool_modules

from .service_clients import claims, fake_service
from .test_module_roles import ACCESS, MODULES
from .test_review_decisions import signed_in  # noqa: F401  # pyright: ignore[reportUnusedImport]


async def _events(engine: AsyncEngine, tenant: str) -> list[dict[str, Any]]:
    async with engine.connect() as c:
        q = sa.select(service_outbox).where(service_outbox.c.tenant_id == tenant).order_by(service_outbox.c.created_at)
        return [dict(r) for r in (await c.execute(q)).mappings()]


async def test_a_request_writes_its_event_for_the_deciding_team_and_the_asker(
    signed_in: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    c, people = signed_in
    r = await c.post(f"{MODULES}/mod_core_banking/approvals", json=ACCESS, headers=people["james"])
    assert r.status_code == 201, r.text
    approval = r.json()["data"]
    assert approval["reviewId"] == f"tool_access.requested:{approval['id']}"
    [event] = await _events(engine, tenant)
    assert (event["name"], event["event_key"], event["team_id"]) == (
        "tool_access.requested",
        approval["id"],
        approval["deciderTeam"],
    )
    assert event["actor"] == "james@bank.example", "the asker, so the requester rule has someone to refuse"
    p = event["payload"]
    assert (p["moduleId"], p["approvalId"], p["workflowId"], p["operations"]) == (
        "mod_core_banking",
        approval["id"],
        ACCESS["workflowId"],
        ACCESS["operations"],
    )


async def test_a_refused_request_leaves_no_event(
    signed_in: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    c, people = signed_in
    assert (await c.post(f"{MODULES}/mod_core_banking/approvals", json=ACCESS, headers=people["james"])).is_success
    again = await c.post(f"{MODULES}/mod_core_banking/approvals", json=ACCESS, headers=people["james"])
    assert again.status_code == 409, again.text
    assert len(await _events(engine, tenant)) == 1


async def test_the_relay_posts_each_event_to_agents_service_for_its_tenant_and_team() -> None:
    got: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        c = claims(request)
        got.append(
            {"path": request.url.path, "tenant": c["tenant_id"], "team": c["team_id"], "scopes": c.get("scopes")}
        )
        got[-1]["body"] = json.loads(request.content)
        return httpx.Response(202, json={"success": True, "data": {"status": "started"}})

    body = {"name": "tool_access.requested", "key": "apr_1", "teamId": "team_ops", "payload": {"approvalId": "apr_1"}}
    await sender(fake_service(handler, "agents", ["events:emit"]))({"tenantId": "local", "body": body})
    assert got == [
        {"path": "/v1/events", "tenant": "local", "team": "team_ops", "scopes": ["events:emit"], "body": body}
    ], got


async def test_a_request_for_a_module_no_team_owns_is_refused_plainly(
    signed_in: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    """A workspace-level module (the platform's tools, c-433) serves every team's runs with no grant, and no team
    would decide a request for it: the asker is told so, not answered 500 (c-439)."""
    c, people = signed_in
    m, o = tool_modules, module_operations
    async with engine.connect() as conn:
        q = sa.select(m.c.id, o.c.name).join(o, (o.c.module_id == m.c.id) & (o.c.tenant_id == m.c.tenant_id))
        found = (await conn.execute(q.where(m.c.tenant_id == tenant, m.c.team_id.is_(None)))).first()
    assert found is not None, "the seed holds a module no team owns"
    module, operation = found
    body = ACCESS | {"operations": [operation]}
    r = await c.post(f"{MODULES}/{module}/approvals", json=body, headers=people["james"])
    assert r.status_code == 422, r.text
    assert "belongs to no team" in r.json()["error"]["message"], r.text
    assert await _events(engine, tenant) == []
