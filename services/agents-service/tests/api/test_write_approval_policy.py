"""The review service applies each operation's write approval policy (c-048 T005), by failure mode: the person who
asked approving their own write after the tenant switched requesterMayDecide off (c-186), read from the platform
token, or refused while it is open; the workspace's stepUp policy not asking for a step-up on a write whose operation
asks for none. Who decides is the thread's team (c-509): test_approval_in_the_runs_team.py. tools-service's
side (the policy, and OPA counting approvers) is tested there; here the policy is what tools-service would answer."""

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
from ops_engine.store import metadata as engine_metadata
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import Ed25519Signer, mint
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model, sse_events, step_up

PLATFORM = Ed25519Signer.generate("platform-test")
WRITE = 'call request_document {"customerId": "C-1042", "document": "proof of address", "reason": "Moved"}'


def person(
    sub: str, teams: list[str], *, auth_method: str | None = None, policies: dict[str, Any] | None = None
) -> dict[str, str]:
    """`auth_method="dev"` is a person platform-service signed in with the dev password, as on a dev stack."""
    claims = {
        "sub": sub,
        "email": f"{sub}@harborpine.example",
        "name": sub,
        "kind": "person",
        "aud": ["agents"],
        "tenant_id": "acme",
        "team_ids": teams,
        "roles": dict.fromkeys(teams, "approver"),
        **({"auth_method": auth_method} if auth_method else {}),
        **({"policies": policies} if policies is not None else {}),
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": teams[0]}


async def jwks() -> dict[str, Any]:
    return {"keys": [PLATFORM.public_jwk()]}


async def introspect(_key: str) -> dict[str, Any] | None:
    return None


async def _client(settings: Settings, *, platform: bool) -> AsyncIterator[AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
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
        knowledge=fixture_knowledge(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        app.state.runtime.team_names = _Names()
        yield client


class _Names:
    """Team names as platform-service answers them (team_names.PlatformTeamNames)."""

    async def name(self, team_id: str) -> str | None:
        return {"team_ops": "Operations", "team_fraud": "Fraud Operations"}.get(team_id)


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
    )
    async for c in _client(settings, platform=True):
        yield c


@pytest.fixture
async def dev_platform() -> AsyncIterator[AsyncClient]:
    async for c in _client(Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED), platform=True):
        yield c


def policy() -> Callable[..., Any]:
    async def fake(_rt: Any, _tool: str) -> WritePolicy:
        return WritePolicy("write", 1)

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


async def test_the_asker_approves_their_own_write_until_the_tenant_switches_it_off(production: AsyncClient) -> None:
    james = person("usr_james", ["team_ops"])
    url = await drafted(production, james)
    assert (await production.post(url, json={"type": "approve"}, headers=james)).status_code == 200

    strict = {"requesterMayDecide": False}
    james, maya = person("usr_james", ["team_ops"], policies=strict), person("usr_maya", ["team_ops"], policies=strict)
    url = await drafted(production, james)
    own = await production.post(url, json={"type": "approve"}, headers=james)
    assert (own.status_code, own.json()["error"]["code"]) == (403, "own_request"), own.text
    assert (await production.post(url, json={"type": "approve"}, headers=maya)).status_code == 200


async def test_a_chat_write_says_what_approving_does_and_which_team_decides(
    dev_platform: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The showcase run: a write drafted in chat showed an empty "If you approve" card and never said who decides."""
    monkeypatch.setattr(hitl_facade, "policy_of", policy())
    james = person("usr_james", ["team_ops"])
    thread = (await drafted(dev_platform, james)).split("/")[3]
    review = (await dev_platform.get(f"/reviews/{thread}", headers=james)).json()["data"]
    assert (
        review["consequence"] == "Ask a customer to provide a document (receipt, statement, proof of address, ID)."
    ), review
    assert {"label": "Document", "value": "proof of address"} in review["actionFields"], review["actionFields"]
    assert review["decidingTeam"] == {"id": "team_ops", "name": "Operations"}, review


async def test_a_person_signed_in_with_the_dev_password_approves_only_in_the_threads_team(
    dev_platform: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dev stack signs people in through platform-service with the demo password; they keep their teams, unlike the
    dev header caller, so a Fraud Operations approver does not reach Operations' write, and Operations' does."""
    monkeypatch.setattr(hitl_facade, "policy_of", policy())
    url = await drafted(dev_platform, person("usr_james", ["team_ops"], auth_method="dev"))
    omar = person("usr_omar", ["team_fraud"], auth_method="dev")
    assert (await dev_platform.post(url, json={"type": "approve"}, headers=omar)).status_code == 404
    maya = person("usr_maya", ["team_ops"], auth_method="dev")
    r = await dev_platform.post(url, json={"type": "approve"}, headers=maya)
    assert r.status_code == 200, r.text


async def test_the_workspace_step_up_policy_asks_every_approver_to_step_up() -> None:
    dana = {"X-Dev-User": "dana@harborpine.example"}
    async for c in _client(Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED), platform=False):
        # The operation asks for no step-up and the policy is open: approving needs none.
        assert (await c.post(await drafted(c, dana), json={"type": "approve"}, headers=dana)).status_code == 200
    strict = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED, dev_policies={"stepUp": True})
    async for c in _client(strict, platform=False):
        url = await drafted(c, dana)
        bare = await c.post(url, json={"type": "approve"}, headers=dana)
        assert (bare.status_code, bare.json()["error"]["code"]) == (422, "step_up_required"), bare.text
        token = await step_up(c, "dana@harborpine.example")
        stepped = await c.post(url, json={"type": "approve", "stepUpToken": token}, headers=dana)
        assert stepped.status_code == 200, stepped.text
