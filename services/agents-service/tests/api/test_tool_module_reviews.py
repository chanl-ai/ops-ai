"""Tool module reviews as publish requests (c-163), by failure mode: a person or another service opening one, a body
naming a team other than the person's, tools-service's own token naming who asked for another kind or without its scope
(c-222), the requester or an approver
outside Security approving a security change, and an approval that never reaches tools-service."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_engine.store import metadata as engine_metadata
from ops_identity import Auth, Identity, ServiceAuth, dev_service_signer, mint_service_token, service_verifiers
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model
from tests.engine.test_lifecycle_rights import BUILDER, TENANT, introspect, jwks, person

SECURITY = person("nadia", "team_security", "approver")
OPS_APPROVER = person("maya", "team_ops", "approver")
BODY = {
    "kind": "tool_module",
    "subjectId": "mod_core_banking",
    "moduleName": "Core banking",
    "moduleVersion": "3.0.0",
    "changes": [{"operation": "transfer_funds", "kind": "policy", "detail": "Two approvers", "major": True}],
    "security": True,
}


def service(name: str, team: str | None = None) -> str:
    token = mint_service_token(dev_service_signer(), service=name, audience="agents", tenant_id=TENANT, team_id=team)
    return f"Bearer {token}"


class FakeTools:
    """tools-service's review-decisions route: records what Reviews sent, or fails while `down`."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.down = False

    async def review_decision(self, module_id: str, decision: dict[str, Any]) -> None:
        if self.down:
            raise RuntimeError("tools-service is down")
        self.sent.append((module_id, decision))


@pytest.fixture
async def stack() -> AsyncIterator[tuple[AsyncClient, FakeTools]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED, registry_auto_approve=False)
    # Service tokens resolve on the public routes as well as the service ones, as in a deployment (c-222).
    services = ServiceAuth(
        audience="agents", verifiers=service_verifiers(settings, "agents"), scopes=settings.service_scopes
    )
    auth = Auth(
        Identity(audience="agents", jwks=jwks, introspect=introspect, key_cache_s=0, services=services), services
    )
    app = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        auth=auth,
        knowledge=fixture_knowledge(),
    )
    tools = FakeTools()
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        app.state.runtime.tool_reviews = tools
        yield c, tools


async def _open(c: AsyncClient, body: dict[str, Any] = BODY) -> Any:
    return await c.post(
        "/v1/publish-requests", json=body, headers={**BUILDER, "X-Service-Authorization": service("tools")}
    )


async def test_only_tools_service_opens_a_review_for_the_person_and_their_team(
    stack: tuple[AsyncClient, FakeTools],
) -> None:
    c, _ = stack
    bare = await c.post("/v1/publish-requests", json=BODY, headers=BUILDER)
    assert (bare.status_code, bare.json()["error"]["code"]) == (401, "service_required"), bare.text
    other = await c.post(
        "/v1/publish-requests", json=BODY, headers={**BUILDER, "X-Service-Authorization": service("kb")}
    )
    assert (other.status_code, other.json()["error"]["code"]) == (403, "service_required"), other.text
    elsewhere = await _open(c, {**BODY, "teamId": "team_fraud"})
    assert (elsewhere.status_code, elsewhere.json()["error"]["code"]) == (403, "team_forbidden"), elsewhere.text
    opened = await _open(c)
    assert opened.status_code == 201, opened.text
    review = opened.json()["data"]
    assert review["id"].startswith("TMP-") and review["status"] == "pending"
    assert review["customer"] == "Requested by james@harborpine.example" and review["policy"]["reviewers"] == "Security"


async def test_security_decides_a_security_change_and_the_decision_reaches_tools_service(
    stack: tuple[AsyncClient, FakeTools],
) -> None:
    c, tools = stack
    rid = (await _open(c)).json()["data"]["id"]
    decision = f"/v1/publish-requests/{rid}/decision"
    own = await c.post(decision, json={"decision": "approved"}, headers=BUILDER)
    assert own.status_code == 403, own.text
    outside = await c.post(decision, json={"decision": "approved"}, headers=OPS_APPROVER)
    assert outside.status_code == 403, outside.text
    tools.down = True
    approved = await c.post(decision, json={"decision": "approved"}, headers=SECURITY)
    assert approved.status_code == 200 and approved.json()["data"]["toolModule"]["applyPending"] is True, approved.text
    assert tools.sent == []
    tools.down = False
    again = await c.get(f"/v1/publish-requests/{rid}", headers=SECURITY)
    assert again.json()["data"]["toolModule"]["applyPending"] is False
    assert tools.sent == [("mod_core_banking", {**tools.sent[0][1], "decision": "approved", "version": "3.0.0"})]


async def test_tools_service_alone_opens_a_tool_module_review_on_a_persons_behalf_and_nothing_else(
    stack: tuple[AsyncClient, FakeTools],
) -> None:
    """Its seed's versions waiting for review (c-222): tools-service's own token scoped to the module's team, with
    tools:publish, opens a tool module review naming who asked, recorded as opened on their behalf. A person's token
    cannot name someone else, tools-service cannot open another kind, and no other service opens one."""
    c, _ = stack
    asked = {**BODY, "requestedBy": "james@harborpine.example"}

    def token(name: str, scopes: list[str]) -> dict[str, str]:
        minted = mint_service_token(
            dev_service_signer(), service=name, audience="agents", tenant_id=TENANT, team_id="team_ops", scopes=scopes
        )
        return {"Authorization": f"Bearer {minted}"}

    opened = await c.post("/v1/publish-requests", json=asked, headers=token("tools", ["tools:publish"]))
    assert opened.status_code == 201, opened.text
    review = opened.json()["data"]
    assert review["customer"] == "Requested by tools-service on behalf of james@harborpine.example", review
    person = await c.post(
        "/v1/publish-requests", json=asked, headers={**BUILDER, "X-Service-Authorization": service("tools")}
    )
    assert (person.status_code, person.json()["error"]["code"]) == (400, "requested_by_forbidden"), person.text
    agent = await c.post(
        "/v1/publish-requests", json={**asked, "kind": "agent"}, headers=token("tools", ["tools:publish"])
    )
    assert agent.status_code in (400, 422), agent.text
    # Only tools-service's scope cap allows tools:publish: another service's token claiming it is refused outright, and
    # one without it is refused by the scope the route asks.
    claimed = await c.post("/v1/publish-requests", json=asked, headers=token("kb", ["tools:publish"]))
    assert claimed.status_code == 401, claimed.text
    other = await c.post("/v1/publish-requests", json=asked, headers=token("kb", []))
    assert (other.status_code, other.json()["error"]["code"]) == (403, "scope_required"), other.text
    unscoped = await c.post(
        "/v1/publish-requests", json={**asked, "subjectId": "mod_cards"}, headers=token("tools", [])
    )
    assert unscoped.status_code == 403, unscoped.text


async def test_the_review_keeps_and_shows_what_tools_service_said_it_approves(
    stack: tuple[AsyncClient, FakeTools],
) -> None:
    """c-204: the diff sent at open is stored with the review and returned as asked, so the reviewer sees the
    operations, hosts and secrets of the version requested, even if the module is edited afterwards."""
    c, _ = stack
    diff = {
        "added": [{"name": "get_statement", "method": "GET", "path": "/v1/statements", "access": "read"}],
        "removed": [],
        "changed": [
            {"name": "get_balance", "method": "GET", "path": "/v2/balance", "access": "read", "fields": ["path"]}
        ],
        "hostsAdded": ["statements.example.com"],
        "secrets": ["STATEMENTS_KEY"],
    }
    opened = await _open(c, {**BODY, "diff": diff})
    assert opened.status_code == 201, opened.text
    review = await c.get(f"/reviews/{opened.json()['data']['id']}", headers=SECURITY)
    assert review.status_code == 200, review.text
    assert review.json()["data"]["toolModule"]["diff"] == diff
