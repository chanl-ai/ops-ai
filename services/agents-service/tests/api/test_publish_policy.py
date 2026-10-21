"""Publish reviews as a setting (c-086), by failure mode: a non-admin turning reviews off, a stale save overwriting
another admin's, "never" leaving no record of who published, a security change slipping through as minor, a first
publish skipping review, dev auto-approve overriding an explicit "always", and the graph versions route ignoring the
policy."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, ClassVar

import pytest
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api import publish_policy
from ops_agents.api.app import create_app, service_client
from ops_agents.api.platform_policies import PlatformPolicies, PolicyUnread
from ops_agents.api.publish_policy import is_major
from ops_agents.store.base import metadata
from ops_agents.store.tenancy import current_tenant
from ops_engine.store import metadata as engine_metadata
from ops_identity import Auth, Identity, ServiceAuth, ServiceClient, dev_service_signer, service_verifiers
from ops_service_kit.settings import Settings
from tests.api.test_graph_versions import definition as graph_definition
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model
from tests.engine.test_lifecycle_rights import ADMIN, BUILDER, introspect, jwks


async def _stack(auto: bool) -> AsyncIterator[AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED, registry_auto_approve=auto)
    auth = Auth(
        Identity(audience="agents", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="agents", verifiers=service_verifiers(settings, "agents")),
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
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
        AsyncClient(transport=MockTransport(platform), base_url="http://platform") as policies,
    ):
        reader = ServiceClient(
            policies, dev_service_signer(), "agents", "platform", ["settings:view"], tenant=current_tenant
        )
        app.state.runtime.policies = PlatformPolicies(reader)
        yield c


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Dev auto-approve off, as every deployed environment runs."""
    async for c in _stack(False):
        yield c


@pytest.fixture
async def dev_client() -> AsyncIterator[AsyncClient]:
    async for c in _stack(True):
        yield c


def _data(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"]


# The workspace's publishReview setting as platform-service would answer it (c-214): decide reads it live on every
# publish, so a change here applies to the next request.
class Platform:
    modes: ClassVar[dict[str, str]] = {}
    down: ClassVar[bool] = False


def platform(_request: Request) -> Response:
    if Platform.down:
        return Response(503, json={"success": False})
    value = {"team_ops": dict(Platform.modes)}
    return Response(200, json={"success": True, "data": {"key": "publishReview", "value": value}})


@pytest.fixture(autouse=True)
def fresh_modes() -> None:
    Platform.modes.clear()
    Platform.down = False


async def set_mode(_c: AsyncClient, area: str, mode: str) -> None:
    Platform.modes[area] = mode


async def agent_at_v2(c: AsyncClient, patch: dict[str, Any] | None = None) -> tuple[str, int]:
    """An agent whose v1 is published (under "never", so no reviewer is needed) and a v2 draft carrying `patch`."""
    await set_mode(c, "agents", "never")
    a = _data(await c.post("/v1/agents", json={"name": "Payee checker", "role": "Checks payees"}, headers=BUILDER), 201)
    _data(await c.post(f"/v1/agents/{a['id']}/publish-requests", json={"version": 1}, headers=BUILDER), 201)
    v = _data(await c.patch(f"/v1/agents/{a['id']}", json=patch or {"role": "Checks new payees"}, headers=BUILDER))
    return a["id"], int(v["version"])


async def test_never_publishes_at_once_and_records_who(client: AsyncClient) -> None:
    aid, v = await agent_at_v2(client, {"toolIds": ["lookup_account"]})
    review = _data(await client.post(f"/v1/agents/{aid}/publish-requests", json={"version": v}, headers=BUILDER), 201)
    assert review["status"] == "approved", review
    body = review["agentPublish"]
    assert (body["reviewRequired"], body["policy"], body["majorChange"]) == (False, "never", True)
    assert body["requestedBy"] == "james@harborpine.example"
    assert _data(await client.get(f"/v1/agents/{aid}", headers=BUILDER))["publishedVersion"] == v


async def test_major_reviews_a_security_change_and_publishes_a_minor_one(client: AsyncClient) -> None:
    aid, v = await agent_at_v2(client)
    await set_mode(client, "agents", "major")
    minor = _data(await client.post(f"/v1/agents/{aid}/publish-requests", json={"version": v}, headers=BUILDER), 201)
    assert (minor["status"], minor["agentPublish"]["majorChange"]) == ("approved", False), minor
    tools = _data(await client.patch(f"/v1/agents/{aid}", json={"toolIds": ["lookup_account"]}, headers=BUILDER))
    major = await client.post(f"/v1/agents/{aid}/publish-requests", json={"version": tools["version"]}, headers=BUILDER)
    body = _data(major, 201)
    assert (body["status"], body["agentPublish"]["reviewRequired"]) == ("pending", True), body


async def test_always_opens_a_review_even_for_a_rename(client: AsyncClient) -> None:
    aid, v = await agent_at_v2(client)
    await set_mode(client, "agents", "always")
    review = _data(await client.post(f"/v1/agents/{aid}/publish-requests", json={"version": v}, headers=BUILDER), 201)
    assert (review["status"], review["agentPublish"]["policy"]) == ("pending", "always"), review


async def test_a_registry_workflows_graph_version_follows_the_policy(client: AsyncClient) -> None:
    w = _data(
        await client.post(
            "/v1/workflows", json={"name": "Hold check", "trigger": "Manual", "template": "blank"}, headers=BUILDER
        ),
        201,
    )
    refused = await client.post(
        f"/v1/graphs/{w['id']}/versions", json={"definition": graph_definition(1)}, headers=BUILDER
    )
    assert (refused.status_code, refused.json()["error"]["code"]) == (409, "review_required"), refused.text
    await set_mode(client, "workflows", "never")
    ok = await client.post(f"/v1/graphs/{w['id']}/versions", json={"definition": graph_definition(1)}, headers=BUILDER)
    assert ok.status_code == 201, ok.text


def test_first_publishes_guardrails_and_approval_fields_are_always_major(monkeypatch: pytest.MonkeyPatch) -> None:
    assert is_major("agents", None, {"name": "x"})
    assert is_major("guardrails", {"topics": ["a"]}, {"topics": ["a"]})
    # Even an area that someday lists access as minor cannot publish an access change unreviewed.
    monkeypatch.setitem(publish_policy.MINOR_FIELDS, "workflows", frozenset({"name", "access"}))
    assert is_major("workflows", {"name": "a", "access": "read"}, {"name": "a", "access": "write"})
    assert not is_major("agents", {"name": "a", "role": "r"}, {"name": "b", "role": "r2"})


async def test_dev_auto_approve_publishes_major_but_not_always(dev_client: AsyncClient) -> None:
    c = dev_client
    aid, v = await agent_at_v2(c, {"toolIds": ["lookup_account"]})
    await set_mode(c, "agents", "major")
    auto = _data(await c.post(f"/v1/agents/{aid}/publish-requests", json={"version": v}, headers=BUILDER), 201)
    assert auto["status"] == "approved", auto
    again = _data(await c.patch(f"/v1/agents/{aid}", json={"role": "Again"}, headers=BUILDER))
    await set_mode(c, "agents", "always")
    review = _data(
        await c.post(f"/v1/agents/{aid}/publish-requests", json={"version": again["version"]}, headers=BUILDER), 201
    )
    assert review["status"] == "pending", review


async def test_never_still_reviews_a_guardrail_and_an_agents_guardrail_change(client: AsyncClient) -> None:
    await set_mode(client, "guardrails", "never")
    rule = {"name": "No tax advice", "topics": ["tax advice"], "message": "I can't give tax advice."}
    g = _data(await client.post("/v1/guardrails", json=rule, headers=BUILDER), 201)
    sent = _data(
        await client.post(f"/v1/guardrails/{g['id']}/publish-requests", json={"version": 1}, headers=BUILDER), 201
    )
    assert sent["pendingRequestId"], sent
    decision = f"/v1/guardrails/{g['id']}/publish-requests/{sent['pendingRequestId']}/decision"
    _data(await client.post(decision, json={"decision": "approved"}, headers=ADMIN))
    pins = {"guardrailPins": [{"guardrailId": g["id"], "version": 1}]}
    aid, v = await agent_at_v2(client, pins)
    pinned = _data(await client.post(f"/v1/agents/{aid}/publish-requests", json={"version": v}, headers=BUILDER), 201)
    assert (pinned["status"], pinned["agentPublish"]["policy"]) == ("pending", "never"), pinned


async def _deployment(c: AsyncClient) -> tuple[str, str]:
    """A published agent and a widget deployment of it on one origin."""
    aid, _ = await agent_at_v2(c)
    d = _data(
        await c.post(
            "/v1/widget-deployments",
            json={"agentId": aid, "name": "Intranet chat", "origins": ["https://intranet.example"]},
            headers=BUILDER,
        ),
        201,
    )
    return aid, d["id"]


async def test_a_deployments_new_origin_waits_for_review_under_never_and_applies_on_approval(
    client: AsyncClient,
) -> None:
    _, did = await _deployment(client)
    await set_mode(client, "agents", "never")
    origins = {"origins": ["https://intranet.example", "https://staff.example"]}
    waits = _data(await client.patch(f"/v1/channels/{did}", json=origins, headers=BUILDER), 202)["reviewId"]
    listed = _data(await client.get("/v1/widget-deployments", headers=BUILDER))
    assert next(d for d in listed if d["id"] == did)["origins"] == ["https://intranet.example"]
    review = _data(await client.get(f"/v1/publish-requests/{waits}", headers=ADMIN))
    assert review["reasoning"] == ["Allow https://staff.example"], review
    _data(await client.post(f"/v1/publish-requests/{waits}/decision", json={"decision": "approved"}, headers=ADMIN))
    listed = _data(await client.get("/v1/widget-deployments", headers=BUILDER))
    assert next(d for d in listed if d["id"] == did)["origins"] == origins["origins"]


async def test_a_rejected_origin_change_leaves_the_deployment_as_it_was(client: AsyncClient) -> None:
    _, did = await _deployment(client)
    other = {"origins": ["https://other.example"]}
    waits = _data(await client.patch(f"/v1/channels/{did}", json=other, headers=BUILDER), 202)["reviewId"]
    decision = {"decision": "rejected", "reason": "Not a bank origin"}
    _data(await client.post(f"/v1/publish-requests/{waits}/decision", json=decision, headers=ADMIN))
    listed = _data(await client.get("/v1/widget-deployments", headers=BUILDER))
    assert next(d for d in listed if d["id"] == did)["origins"] == ["https://intranet.example"]


async def test_moving_a_deployment_follows_the_agents_setting_as_a_minor_change(client: AsyncClient) -> None:
    aid, did = await _deployment(client)
    v = _data(await client.patch(f"/v1/agents/{aid}", json={"role": "Checks payees again"}, headers=BUILDER))
    _data(await client.post(f"/v1/agents/{aid}/publish-requests", json={"version": v["version"]}, headers=BUILDER), 201)
    await set_mode(client, "agents", "major")
    latest = {"serves": {"kind": "agent", "id": aid, "version": "latest"}}
    moved = _data(await client.patch(f"/v1/channels/{did}", json=latest, headers=BUILDER))["serves"]
    assert (moved["version"], moved["latestVersion"]) == ("latest", v["version"]), moved


async def test_never_still_reviews_switching_pii_redaction_off(client: AsyncClient) -> None:
    off: dict[str, Any] = {
        "redactPii": False,
        "maxToolCallsPerTurn": None,
        "maxModelCallsPerTurn": 50,
        "whenUnsure": "handoff",
        "blockedTopics": [],
    }
    aid, v = await agent_at_v2(client, {"guardrails": off})
    review = _data(await client.post(f"/v1/agents/{aid}/publish-requests", json={"version": v}, headers=BUILDER), 201)
    assert (review["status"], review["agentPublish"]["policy"]) == ("pending", "never"), review


async def test_the_publish_preview_says_what_the_publish_then_does(dev_client: AsyncClient) -> None:
    """agents-1: the dialog promised a review the dev stack never opened. The preview and the publish share one
    decision."""
    c = dev_client
    aid, v = await agent_at_v2(c, {"toolIds": ["lookup_account"]})
    await set_mode(c, "agents", "major")
    preview = _data(await c.get(f"/v1/agents/{aid}/publish-preview", params={"version": v}, headers=BUILDER))
    assert (preview["reviewRequired"], preview["reviewReason"]) == (False, "dev_auto_approve"), preview
    live = _data(await c.post(f"/v1/agents/{aid}/publish-requests", json={"version": v}, headers=BUILDER), 201)
    assert live["status"] == "approved", live
    again = _data(await c.patch(f"/v1/agents/{aid}", json={"role": "Again"}, headers=BUILDER))
    await set_mode(c, "agents", "always")
    ask = {"version": again["version"]}
    preview = _data(await c.get(f"/v1/agents/{aid}/publish-preview", params=ask, headers=BUILDER))
    assert (preview["reviewRequired"], preview["reviewReason"]) == (True, "policy_always"), preview
    waiting = _data(await c.post(f"/v1/agents/{aid}/publish-requests", json=ask, headers=BUILDER), 201)
    assert waiting["status"] == "pending", waiting


async def test_a_changed_setting_applies_to_the_very_next_publish(client: AsyncClient) -> None:
    """No wait for a token refresh or a cache. A rename publishes at once under the default; once the
    team reviews every agents publish, the next rename waits, with no new sign-in."""
    a = _data(await client.post("/v1/agents", json={"name": "Renamer", "role": "Renames"}, headers=BUILDER), 201)
    await set_mode(client, "agents", "never")
    first = _data(
        await client.post(f"/v1/agents/{a['id']}/publish-requests", json={"version": 1}, headers=BUILDER), 201
    )
    assert first["status"] == "approved", first
    await set_mode(client, "agents", "major")
    v2 = _data(await client.patch(f"/v1/agents/{a['id']}", json={"name": "Renamed"}, headers=BUILDER))["version"]
    minor = _data(
        await client.post(f"/v1/agents/{a['id']}/publish-requests", json={"version": v2}, headers=BUILDER), 201
    )
    assert minor["status"] == "approved", minor
    await set_mode(client, "agents", "always")
    v3 = _data(await client.patch(f"/v1/agents/{a['id']}", json={"name": "Renamed again"}, headers=BUILDER))["version"]
    held = _data(
        await client.post(f"/v1/agents/{a['id']}/publish-requests", json={"version": v3}, headers=BUILDER), 201
    )
    assert (held["status"], held["agentPublish"]["policy"]) == ("pending", "always"), held


async def test_an_unreadable_setting_opens_a_review(client: AsyncClient) -> None:
    a = _data(await client.post("/v1/agents", json={"name": "Renamer", "role": "Renames"}, headers=BUILDER), 201)
    await set_mode(client, "agents", "never")
    _data(await client.post(f"/v1/agents/{a['id']}/publish-requests", json={"version": 1}, headers=BUILDER), 201)
    v2 = _data(await client.patch(f"/v1/agents/{a['id']}", json={"name": "Renamed"}, headers=BUILDER))["version"]
    Platform.down = True
    held = _data(
        await client.post(f"/v1/agents/{a['id']}/publish-requests", json={"version": v2}, headers=BUILDER), 201
    )
    assert (held["status"], held["agentPublish"]["reviewReason"]) == ("pending", "policy_unread"), held


async def test_a_process_with_no_signing_key_reads_no_policy_and_so_reviews() -> None:
    """Outside dev with no service signing key the service still starts, and an unread policy opens a review."""
    # A copy skips the validators that refuse dev auth in production: only the signing key matters here.
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED).model_copy(
        update={"environment": "production"}
    )
    async with AsyncClient(base_url="http://platform") as http:
        reader = PlatformPolicies(service_client(settings, http, "platform"))
        with pytest.raises(PolicyUnread):
            await reader.value("publishReview")
