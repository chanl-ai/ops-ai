"""A tool's own approvalMode, by failure mode: a loosening (don't ask, ask the person) staged as a minor edit that
reaches calls without Security; a published tool's mode ignored where its team asks a reviewer; a tool with no mode
losing to a team that asks; and a mode saved on a read. Driven through the real routes and the real gateway, with the
team's switch held by a fake that asks a reviewer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.modules.policy import WriteApprovals
from ops_tools.modules.seed import load
from ops_tools.store.event_relay import sender
from ops_tools.store.modules import ModuleStore, service_outbox

from .conftest import Api, build_app, opa_client, response_checker, service_headers
from .service_clients import fake_service

MOD = "/mod_core_banking"
ADDRESS = {
    "customerId": "CUS-1001",
    "line1": "12 Harbour Street",
    "city": "Halifax",
    "province": "NS",
    "postalCode": "B3J 1A1",
}


class TeamAsksReviewer(WriteApprovals):
    """A team whose switch is on and answered by a reviewer, no app overriding it."""

    def __init__(self) -> None:
        super().__init__(None)
        # What an admin saved in appChangesByApp; a test fills it as the Approvals page would.
        self.by_app: dict[str, Any] = {}

    async def levels(self, tenant_id: str, team_id: str | None) -> tuple[Any, dict[str, Any]]:
        return {"ask": True, "answer": "reviewer", "reviewerRole": None, "testAccountsNeverAsk": True}, self.by_app


@pytest.fixture
def team() -> TeamAsksReviewer:
    return TeamAsksReviewer()


@pytest.fixture
async def asking(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]], team: TeamAsksReviewer
) -> AsyncIterator[Api]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    async with opa_client() as opa:
        app = build_app(engine, seed, tenant, opa=opa, write_approvals=team)
        hooks = {"response": [response_checker(app)]}
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks) as c,
        ):
            yield Api(c, tenant)


async def _op(api: Api, name: str) -> dict[str, Any]:
    detail = (await api.call("GET", MOD)).json()["data"]
    return next(o for o in detail["operations"] if o["name"] == name)


async def _set(api: Api, name: str, body: dict[str, Any]) -> dict[str, Any]:
    op = await _op(api, name)
    r = await api.call("PATCH", f"{MOD}/operations/{op['id']}", json=body)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _changes(detail: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [c for c in detail["pendingChanges"] if c["operation"] == name and c["kind"] == "settings"]


async def _grantable(api: Api) -> dict[str, dict[str, Any]]:
    r = await api.client.get("/v1/grantable-operations", headers=service_headers(api.tenant))
    assert r.status_code == 200, r.text
    return {str(o["name"]): o for o in r.json()["data"]}


async def _publish_and_decide(api: Api) -> httpx.Response:
    posted = await api.call("POST", f"{MOD}/versions", json={"note": "Approval mode"})
    assert posted.status_code == 200, posted.text
    return await api.decide(MOD)


async def test_a_loosening_is_staged_major_and_a_stricter_answer_minor(asking: Api) -> None:
    await _set(asking, "update_address", {"approvalMode": None})  # the seed gives a declared wait "reviewer"
    strict = await _set(asking, "update_address", {"approvalMode": "reviewer"})
    assert [c["major"] for c in _changes(strict, "update_address")] == [False], strict["pendingChanges"]
    quiet = await _set(asking, "update_address", {"approvalMode": "none"})
    assert [c["major"] for c in _changes(quiet, "update_address")][-1] is True, quiet["pendingChanges"]
    person = await _set(asking, "update_address", {"approvalMode": "person"})
    assert [c["major"] for c in _changes(person, "update_address")][-1] is True, person["pendingChanges"]
    assert (await _op(asking, "update_address"))["approvalMode"] == "person"


async def test_a_loosened_tool_waits_for_security_before_calls_see_it(asking: Api) -> None:
    await _set(asking, "update_address", {"approvalMode": "none"})
    # Staged only: calls still see the published tool, which follows the team and waits.
    assert (await _grantable(asking))["update_address"]["answer"] == "reviewer"
    published = await asking.call("POST", f"{MOD}/versions", json={"note": "Run at once"})
    assert published.json()["data"]["versions"][0]["status"] == "in_review", published.text[:300]
    assert (await _grantable(asking))["update_address"]["answer"] == "reviewer", "not live before Security decides"
    assert (await asking.decide(MOD)).status_code == 200
    mine = (await _grantable(asking))["update_address"]
    assert (mine["answer"], mine["source"], mine["requiresApproval"]) == ("none", "tool", False), mine


async def test_the_gateway_follows_the_tools_mode_over_a_team_that_asks(asking: Api) -> None:

    async def call(tool: str, args: dict[str, Any], key: str) -> httpx.Response:
        body = {"tool": tool, "input": args, "key": key, "runContext": {"act": "test"}}
        return await asking.client.post("/v1/calls", json=body, headers=service_headers(asking.tenant))

    waits = await call("update_address", ADDRESS, "m0")
    assert waits.status_code == 403 and "needs an approval token" in waits.text, "the team asks a reviewer"
    await _set(asking, "update_address", {"approvalMode": "none"})
    await _publish_and_decide(asking)
    ran = await call("update_address", ADDRESS, "m1")
    assert ran.status_code == 200 and ran.json()["data"]["decision"] == "allow", ran.text


async def test_a_read_takes_no_approval_mode(asking: Api) -> None:
    op = await _op(asking, "get_customer_profile")
    r = await asking.call("PATCH", f"{MOD}/operations/{op['id']}", json={"approvalMode": "none"})
    assert r.status_code == 422, r.text


async def test_an_admin_loosens_a_tool_whose_default_asks_first_and_the_write_runs(
    asking: Api, team: TeamAsksReviewer
) -> None:
    """A plugin tool's manifest default is a stored reviewer mode on a row no route edits. The admin's answer for the
    tool, kept in the policy store, replaces it without touching the row."""
    assert (await _op(asking, "update_address"))["approvalMode"] == "reviewer", "the seed gives a declared wait this"
    body = {"tool": "update_address", "input": ADDRESS, "runContext": {"act": "test"}}

    async def call(key: str) -> httpx.Response:
        return await asking.client.post("/v1/calls", json={**body, "key": key}, headers=service_headers(asking.tenant))

    waits = await call("p0")
    assert waits.status_code == 403 and "needs an approval token" in waits.text, waits.text
    team.by_app["tool:update_address"] = {"answer": "none"}
    ran = await call("p1")
    assert ran.status_code == 200 and ran.json()["data"]["decision"] == "allow", ran.text
    assert (await _op(asking, "update_address"))["approvalMode"] == "reviewer", "the row is not edited"


async def test_the_older_requires_approval_flag_is_stored_as_the_answer_the_log_describes(asking: Api) -> None:
    """A caller that still sends requiresApproval must not get a "waits" log line the resolver never honours."""
    await _set(asking, "update_address", {"approvalMode": None})
    saved = await _set(asking, "update_address", {"requiresApproval": True})
    assert (await _op(asking, "update_address"))["approvalMode"] == "reviewer"
    assert [c["detail"] for c in _changes(saved, "update_address")] == ["Approval follows the app → asks a reviewer"]
    await _set(asking, "update_address", {"requiresApproval": False})
    assert (await _op(asking, "update_address"))["approvalMode"] is None


async def test_changing_a_tools_answer_tells_agents_to_drop_its_kept_tool_list(
    asking: Api, engine: AsyncEngine, tenant: str
) -> None:
    """Agents keep a team's tool list, which carries each write's answer, for up to 30 s; the edit writes policy.changed
    with the save, and the relay sends it to the route agents-service handles it on."""
    await _set(asking, "update_address", {"approvalMode": "none"})
    async with engine.connect() as c:
        q = sa.select(service_outbox).where(
            service_outbox.c.tenant_id == tenant, service_outbox.c.name == "policy.changed"
        )
        [event] = [dict(r) for r in (await c.execute(q)).mappings()]
    assert event["payload"] == {"key": "tool:update_address"}
    got: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        got.append(request.url.path)
        return httpx.Response(200, json={"success": True, "data": {"handled": True}})

    agents = fake_service(handler, "agents", ["events:emit", "agents:create"])
    await sender(agents)(
        {"tenantId": tenant, "body": {"name": "policy.changed", "key": "k", "teamId": event["team_id"]}}
    )
    assert got == ["/v1/platform-events"]
