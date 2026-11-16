"""Tool module reviews as publish requests, by failure mode: a person or another service opening one, a body
naming a team other than the person's, tools-service's own token naming who asked for another kind or without its scope,
the requester or an approver
outside Security approving a security change, and an approval that never reaches tools-service."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

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


class WorkspaceTeams:
    """platform-service's record of the workspace's Security team, as agents-service reads it (team_names.py)."""

    def __init__(self, security: str | None = "team_security") -> None:
        self.security = security

    async def security_team(self) -> str | None:
        return self.security

    async def name(self, team_id: str) -> str | None:
        return None


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
    # Service tokens resolve on the public routes as well as the service ones, as in a deployment.
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
        app.state.runtime.team_names = WorkspaceTeams()
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
    """Its seed's versions waiting for review: tools-service's own token scoped to the module's team, with
    tools:publish, opens a tool module review naming who asked, the service kept as the one that opened it. A
    person's token cannot name someone else, tools-service cannot open another kind, and no other service opens one."""
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
    # Human Tasks names the person who asked; the service that opened it for them stays on the record.
    assert review["customer"] == "Requested by james@harborpine.example", review
    assert review["toolModule"].get("openedBy") == "tools-service" or "openedBy" not in review["toolModule"], review
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
    """The diff sent at open is stored with the review and returned as asked, so the reviewer sees the
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


async def test_the_workspaces_own_security_team_decides_a_security_change(
    stack: tuple[AsyncClient, FakeTools],
) -> None:
    """The deciding team is the workspace's record, read from platform-service, not a team the install names."""
    c, _ = stack
    c_app = cast(Any, c._transport).app  # pyright: ignore[reportPrivateUsage]
    c_app.state.runtime.team_names = WorkspaceTeams("team_sec2")
    rid = (await _open(c)).json()["data"]["id"]
    decision = f"/v1/publish-requests/{rid}/decision"
    old_team = await c.post(decision, json={"decision": "approved"}, headers=SECURITY)
    assert old_team.status_code == 403, old_team.text
    sec2 = person("noor", "team_sec2", "approver")
    approved = await c.post(decision, json={"decision": "approved"}, headers=sec2)
    assert approved.status_code == 200, approved.text


async def test_a_security_review_is_a_task_of_security_alone(stack: tuple[AsyncClient, FakeTools]) -> None:
    """Publish requests were read per tenant, so another team's Human Tasks listed and counted a security review it
    neither owns nor decides. It is listed in the Security team; the asking team opens it by id; any other team gets
    not found."""
    c, _ = stack
    rid = (await _open(c)).json()["data"]["id"]
    fraud = person("otto", "team_fraud", "approver")

    async def listed(who: dict[str, str]) -> tuple[bool, int]:
        r = await c.get("/reviews", params={"view": "open", "pageSize": 100}, headers=who)
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        return rid in {row["id"] for row in data["data"]}, data["viewCounts"]["open"]

    elsewhere, counted = await listed(fraud)
    assert not elsewhere and counted == 0
    assert (await listed(SECURITY))[0]
    assert (await c.get(f"/reviews/{rid}", headers=fraud)).status_code == 404
    assert (await c.get(f"/v1/publish-requests/{rid}", headers=fraud)).status_code == 404
    assert (await c.get(f"/v1/publish-requests/{rid}", headers=BUILDER)).status_code == 200


async def test_security_reads_a_review_of_another_teams_module_by_id(stack: tuple[AsyncClient, FakeTools]) -> None:
    """Security reviews what another team ships, so it reads the request by id before deciding; a team that neither
    owns, asked nor reviews it gets not found."""
    c, _ = stack
    rid = (await _open(c)).json()["data"]["id"]
    read = await c.get(f"/v1/publish-requests/{rid}", headers=SECURITY)
    assert read.status_code == 200, read.text
    got = {k: v for k, v in read.json()["data"].items() if k not in ("createdAt", "slaMinutes")}
    assert got == {
        "actionTool": "publish_tool_module",
        "agentName": None,
        "agentSlug": "",
        "approvals": [],
        "confidence": 1,
        "currency": "CAD",
        "customer": "Requested by james@harborpine.example",
        "evidence": [],
        "id": "TMP-1001",
        "kind": "publish_request",
        "policy": {
            "condition": "every version before it serves",
            "fourEyes": False,
            "id": "gp_tool_module_review",
            "name": "Tool module review",
            "onTimeout": "Stays pending; the requester is notified",
            "reviewers": "Security",
            "sla": "1 business day",
        },
        "proposal": "",
        "reasoning": ["Two approvers"],
        "risk": "low",
        "status": "pending",
        "title": "Publish Core banking v3.0.0",
        "toolModule": {"applyPending": False, "moduleId": "mod_core_banking", "version": "3.0.0"},
        "workflowId": "",
        "workflowName": "Core banking",
    }
    fraud = person("otto", "team_fraud", "approver")
    assert (await c.get(f"/v1/publish-requests/{rid}", headers=fraud)).status_code == 404


async def test_a_held_host_is_opened_once_and_read_by_security(stack: tuple[AsyncClient, FakeTools]) -> None:
    """A new host is a request for Security: 201 when opened, 200 with the same request while it waits, read by
    Security and the asking team by id and by no other team."""
    c, _ = stack
    headers = {**BUILDER, "X-Service-Authorization": service("tools")}
    body = {"host": "api.ledger.example", "app": "Ledger"}
    opened = await c.post("/v1/publish-requests/egress-hosts", json=body, headers=headers)
    assert opened.status_code == 201, opened.text
    eid = opened.json()["data"]["id"]
    assert eid == "EGH-1001" and opened.json()["data"]["egressHost"] == {
        "app": "Ledger",
        "applyPending": False,
        "host": "api.ledger.example",
        "requestedBy": "james@harborpine.example",
        "teamId": "team_ops",
    }
    again = await c.post("/v1/publish-requests/egress-hosts", json=body, headers=headers)
    assert (again.status_code, again.json()["data"]["id"]) == (200, eid), again.text
    read = await c.get(f"/v1/publish-requests/{eid}", headers=SECURITY)
    assert (read.status_code, read.json()["data"]["policy"]["reviewers"]) == (200, "Security"), read.text
    assert (await c.get(f"/v1/publish-requests/{eid}", headers=BUILDER)).status_code == 200
    fraud = person("otto", "team_fraud", "approver")
    assert (await c.get(f"/v1/publish-requests/{eid}", headers=fraud)).status_code == 404
