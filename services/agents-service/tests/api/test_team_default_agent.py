"""A team's default agent, its specialists and the @mention handover (c-174), by failure mode: someone other than a
team admin changes the default; a chat starts on no default, a default that is not live or another team's agent; the
default agent asks a specialist the person may not chat with, or reaches it by naming the tool; a specialist runs
without the person, or asks another agent; a handover to an agent the person may not chat with or one not live; Back
returns to the wrong agent, or a reload loses who answered. Tokens carry roles as platform-service mints them."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.agent_calls import AgentCalls
from ops_agents.api.app import create_app
from ops_agents.api.auth import Principal
from ops_agents.api.child_runs import acting_for
from ops_agents.api.deps import Runtime
from ops_agents.store.agent_registry import registry_agents
from ops_agents.store.base import metadata
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import metadata as engine_metadata
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_service_kit.settings import Settings
from tests.api.test_action_roles import ADMIN, BUILDER, OUTSIDER, REVIEWER, VIEWER, introspect
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model, sse_events
from tests.engine.test_lifecycle_rights import TENANT, jwks

URL = "/v1/chat/default-agent"
Stack = tuple[AsyncClient, Runtime]


@pytest.fixture
async def stack() -> AsyncIterator[Stack]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED)
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
    ):
        yield c, cast(Runtime, app.state.runtime)


async def move(rt: Runtime, agent_id: str, team: str) -> None:
    """Gives a seeded agent to another team, as a builder of that team would own it."""
    async with rt.db.begin() as c:
        await c.execute(registry_agents.update().where(registry_agents.c.id == agent_id).values(team_id=team))


def viewer() -> Principal:
    return Principal(
        name="vera",
        email="vera@harborpine.example",
        team_id="team_ops",
        tenant_id=TENANT,
        team_ids=("team_ops",),
        role="viewer",
        roles={"team_ops": "viewer"},
    )


async def start(c: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    r = await c.post("/v1/chat/threads", json={"kbIds": []}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def say(c: AsyncClient, thread: str, text: str, headers: dict[str, str]) -> list[dict[str, Any]]:
    r = await c.post(f"/v1/chat/threads/{thread}/messages", json={"content": text}, headers=headers)
    assert r.status_code == 200, r.text
    return sse_events(r.text)


async def test_only_a_team_admin_sets_the_default(stack: Stack) -> None:
    c, _ = stack
    assert "agentId" not in (await c.get(URL, headers=VIEWER)).json()["data"], "no default until one is set"
    refused = [await c.put(URL, json={"agentId": "ag_branch"}, headers=h) for h in (BUILDER, REVIEWER, VIEWER)]
    assert [r.status_code for r in refused] == [403, 403, 403], [r.text for r in refused]
    saved = await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)
    assert saved.status_code == 200, saved.text
    assert (await c.get(URL, headers=VIEWER)).json()["data"] == {
        "agentId": "ag_branch",
        "agentName": "Branch Concierge",
        "canChange": False,
    }
    assert (await c.get(URL, headers=ADMIN)).json()["data"]["canChange"] is True, "the console offers it to admins only"


async def test_a_chat_without_an_agent_starts_only_on_a_live_default_of_the_team(stack: Stack) -> None:
    c, rt = stack
    # A team that has set no default gets its own Ops Assistant on the first chat (c-469), rather than a refusal.
    assert (await start(c, VIEWER))["agentId"] == "ag_ops_team_ops"
    assert (await c.get(URL, headers=VIEWER)).json()["data"]["agentId"] == "ag_ops_team_ops"
    gone = await c.put(URL, json={"agentId": "ag_missing"}, headers=ADMIN)
    assert gone.status_code == 422 and gone.json()["error"]["code"] == "agent_not_live", gone.text
    await move(rt, "ag_fraud", "team_fraud")
    other = await c.put(URL, json={"agentId": "ag_fraud"}, headers=ADMIN)
    assert other.status_code == 422 and other.json()["error"]["code"] == "other_team_agent", other.text
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    assert (await start(c, VIEWER))["agentId"] == "ag_branch"


async def test_the_default_asks_only_specialists_the_person_may_chat_with_and_as_that_person(stack: Stack) -> None:
    c, rt = stack
    await move(rt, "ag_fraud", "team_fraud")  # a viewer of team_ops may not chat with it
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    thread = (await start(c, VIEWER))["id"]
    events = await say(c, thread, 'call agent__ag_dispute {"question": "Can I dispute a card charge?"}', VIEWER)
    ended = [e["call"] for e in events if e.get("type") == "tool_end"]
    assert [(t["name"], t["output"]["status"]) for t in ended] == [("agent__ag_dispute", "answered")], ended
    assert rt.graph_store is not None
    children = [
        t
        for t in await rt.graph_store.threads("agent_wrapper")
        if cast(dict[str, Any], t["meta"] or {}).get("calledBy")
    ]
    assert [(t["meta"]["agentId"], t["meta"]["calledBy"], t["meta"]["startedFor"]) for t in children] == [
        ("ag_dispute", "ag_branch", "vera@harborpine.example")
    ], "the specialist ran its own turn, for the person"
    calls_ = AgentCalls(rt)
    with tenant_scope(TENANT):
        with acting_for(viewer()):
            offered = {g.name for g in await calls_.offers_in("ag_branch", thread)}
            assert "agent__ag_dispute" in offered and "agent__ag_fraud" not in offered, offered
            named = await calls_.run(
                agent="ag_fraud",
                arguments={"question": "x"},
                key="k-fraud",
                parent_thread_id=thread,
                parent_run_id=None,
            )
            assert not named.ok and named.output["code"] == "specialist_not_offered", named.output
            assert await calls_.offers_in("ag_branch", children[0]["id"]) == [], "a specialist asks no other agent"
            assert await calls_.offers_in("ag_dispute", thread) == [], "only the team default asks specialists"
        nobody = await calls_.run(
            agent="ag_dispute", arguments={"question": "x"}, key="k-none", parent_thread_id=thread, parent_run_id=None
        )
        assert not nobody.ok and nobody.output["code"] == "specialist_not_offered", "no person, no specialist"


async def test_a_handover_is_checked_like_a_start_and_back_restores_the_start_agent(stack: Stack) -> None:
    c, rt = stack
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    thread = (await start(c, VIEWER))["id"]
    url = f"/v1/chat/threads/{thread}"
    await move(rt, "ag_fraud", "team_fraud")
    refused = await c.patch(url, json={"agentId": "ag_fraud"}, headers=VIEWER)
    assert refused.status_code == 403, refused.text
    gone = await c.patch(url, json={"agentId": "ag_missing"}, headers=VIEWER)
    assert gone.status_code == 422 and gone.json()["error"]["code"] == "agent_not_live", gone.text
    moved = (await c.patch(url, json={"agentId": "ag_dispute"}, headers=VIEWER)).json()["data"]
    assert (moved["agentId"], moved["startAgentId"]) == ("ag_dispute", "ag_branch"), moved
    await say(c, thread, "Hello", VIEWER)
    back = (await c.patch(url, json={"agentId": "ag_branch"}, headers=VIEWER)).json()["data"]
    assert (back["agentId"], back.get("startAgentId")) == ("ag_branch", None), back
    await say(c, thread, "Hello again", VIEWER)
    reloaded = (await c.get(url, headers=VIEWER)).json()["data"]["messages"]
    answered = [m["agentName"] for m in reloaded if m["role"] == "assistant"]
    assert answered == ["Card Dispute Resolver", "Branch Concierge"], "each reply credits the agent that wrote it"
    assert (await c.patch(url, json={"agentId": "ag_dispute"}, headers=OUTSIDER)).status_code == 404, "not theirs"
