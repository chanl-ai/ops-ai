"""The review service applies each operation's write approval policy (c-048 T005), by failure mode: the person who
asked approving their own write outside dev, an approver from outside the operation's approving team, and the
operation's selfApproval ignored in dev. tools-service's side (the policy, and OPA counting approvers) is tested
there; here the policy is what tools-service would answer."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api import hitl_facade
from ops_agents.api.app import create_app
from ops_agents.api.tool_access import WritePolicy
from ops_agents.store.base import metadata
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_policy import Ed25519Signer, mint
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, scripted_model, sse_events

PLATFORM = Ed25519Signer.generate("platform-test")
WRITE = 'call request_document {"customerId": "C-1042", "document": "proof of address", "reason": "Moved"}'


def person(sub: str, teams: list[str]) -> dict[str, str]:
    claims = {
        "sub": sub,
        "email": f"{sub}@northfield.example",
        "name": sub,
        "kind": "person",
        "aud": ["agents"],
        "tenant_id": "acme",
        "team_ids": teams,
        "roles": dict.fromkeys(teams, "approver"),
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=300)}", "X-Team-Id": teams[0]}


async def jwks() -> dict[str, Any]:
    return {"keys": [PLATFORM.public_jwk()]}


async def introspect(_key: str) -> dict[str, Any] | None:
    return None


async def _client(settings: Settings, *, platform: bool) -> AsyncIterator[AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    auth = (
        Auth(
            Identity(audience="agents", jwks=jwks, introspect=introspect, key_cache_s=0),
            ServiceAuth(audience="agents", verifiers=service_verifiers(settings, "agents")),
        )
        if platform
        else None
    )
    app = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        auth=auth,
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


@pytest.fixture
async def production() -> AsyncIterator[AsyncClient]:
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        seed_dir=SEED,
        environment="production",
        auth_mode="platform",
        platform_url="http://platform.invalid",
        review_key=SecretStr("r" * 40),
        secrets_key=SecretStr("ab" * 32),
        allow_self_approval_in_chat=True,
    )
    async for c in _client(settings, platform=True):
        yield c


@pytest.fixture
async def dev_platform() -> AsyncIterator[AsyncClient]:
    async for c in _client(Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED), platform=True):
        yield c


@pytest.fixture
async def dev_strict() -> AsyncIterator[AsyncClient]:
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED, allow_self_approval_in_chat=False)
    async for c in _client(settings, platform=False):
        yield c


def policy(*, approver_team: str | None = None, self_approval: bool = False) -> Callable[..., Any]:
    async def fake(_rt: Any, _tool: str) -> WritePolicy:
        return WritePolicy("write", 1, approver_team, self_approval)

    return fake


async def drafted(client: AsyncClient, asker: dict[str, str]) -> str:
    """Asks ag_dispute for a write and returns the approval widget's action URL."""
    res = await client.post("/chat/threads", json={"agentId": "ag_dispute", "kbIds": []}, headers=asker)
    assert res.status_code == 201, res.text
    thread = res.json()["data"]["id"]
    sent = await client.post(
        f"/chat/threads/{thread}/messages", json={"content": WRITE}, headers={**asker, "Accept": "text/event-stream"}
    )
    events = sse_events(sent.text)
    widget = next(e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval")
    return f"/chat/threads/{thread}/messages/{events[0]['messageId']}/widgets/{widget['id']}/actions"


async def test_outside_dev_the_asker_never_approves_their_own_write(production: AsyncClient) -> None:
    james, maya = person("usr_james", ["team_ops"]), person("usr_maya", ["team_ops"])
    url = await drafted(production, james)
    own = await production.post(url, json={"type": "approve"}, headers=james)
    assert own.status_code == 403, "allow_self_approval_in_chat is on, but it holds in dev only"
    assert (await production.post(url, json={"type": "approve"}, headers=maya)).status_code == 200


async def test_an_approver_outside_the_approving_team_is_refused(
    dev_platform: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hitl_facade, "policy_of", policy(approver_team="team_fraud"))
    url = await drafted(dev_platform, person("usr_james", ["team_ops"]))
    outside = await dev_platform.post(url, json={"type": "approve"}, headers=person("usr_maya", ["team_ops"]))
    assert outside.status_code == 403 and "team_fraud" in outside.json()["error"]["message"], outside.text
    inside = person("usr_nadia", ["team_ops", "team_fraud"])
    assert (await dev_platform.post(url, json={"type": "approve"}, headers=inside)).status_code == 200


async def test_in_dev_the_operations_self_approval_lets_the_asker_approve(
    dev_strict: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    asker = {"X-Dev-User": "dana@northfieldbank.com"}
    monkeypatch.setattr(hitl_facade, "policy_of", policy(self_approval=False))
    refused = await dev_strict.post(await drafted(dev_strict, asker), json={"type": "approve"}, headers=asker)
    assert refused.status_code == 403
    monkeypatch.setattr(hitl_facade, "policy_of", policy(self_approval=True))
    allowed = await dev_strict.post(await drafted(dev_strict, asker), json={"type": "approve"}, headers=asker)
    assert allowed.status_code == 200, allowed.text
