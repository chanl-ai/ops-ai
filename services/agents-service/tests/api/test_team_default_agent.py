"""A team's default agent, its specialists and the @mention handover, by failure mode: someone other than a
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
from ops_agents.api.ops_tools import ops_assistant_id
from ops_agents.store.agent_registry import registry_agents
from ops_agents.store.base import metadata
from ops_agents.store.events import EventLog
from ops_agents.store.tenancy import LOCAL_TENANT, tenant_scope
from ops_engine.store import metadata as engine_metadata
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_identity import Principal as Caller
from ops_metering import Budget
from ops_service_kit.settings import Settings
from ops_store.isolation import scope
from tests.api.test_action_roles import ADMIN, OUTSIDER, REVIEWER, VIEWER, introspect
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model, sse_events
from tests.engine.test_lifecycle_rights import TENANT, jwks, person

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
        ServiceAuth(audience="agents", verifiers=service_verifiers(settings, "agents"), scopes=settings.service_scopes),
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
    # Builders hold chat.manage since D59; a builder whose role lost it is refused like a reviewer and a viewer.
    no_manage = person("jo", "team_ops", "builder", unticked=(("chat", "manage"),))
    refused = [await c.put(URL, json={"agentId": "ag_branch"}, headers=h) for h in (no_manage, REVIEWER, VIEWER)]
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
    # A team that has set no default gets its own Ops Assistant on the first chat, rather than a refusal.
    assert (await start(c, VIEWER))["agentId"] == ops_assistant_id(LOCAL_TENANT, "team_ops")
    assert (await c.get(URL, headers=VIEWER)).json()["data"]["agentId"] == ops_assistant_id(LOCAL_TENANT, "team_ops")
    # An id the tenant does not hold reads as another tenant's would: not found.
    gone = await c.put(URL, json={"agentId": "ag_missing"}, headers=ADMIN)
    assert gone.status_code == 404 and gone.json()["error"]["code"] == "not_found", gone.text
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
        # Two agents granted each other. The path is what refuses the call back: this specialist's thread carries no
        # `calledBy`, so it is offered the agent that asked it, as a deeper chain would be.
        await grant(c, "ag_dispute", "ag_branch")
        asked_meta = cast(dict[str, Any], children[0]["meta"])
        deeper = {k: v for k, v in asked_meta.items() if k != "calledBy"}
        row, _ = await rt.graph_store.open_thread(
            "th_deeper", "agent_wrapper", deeper, "team_ops", "", external_key="d"
        )
        with acting_for(viewer()):
            assert [g.name for g in await calls_.offers_in("ag_dispute", row.id)] == ["agent__ag_branch"]
            looped = await calls_.run(
                agent="ag_branch",
                arguments={"question": "x"},
                key="k-loop",
                parent_thread_id=row.id,
                parent_run_id=None,
            )
        assert not looped.ok and looped.output["code"] == "agent_on_path", looped.output
        assert await called(rt) == ["ag_branch>ag_dispute"], "an agent already on the path ran again"
        nobody = await calls_.run(
            agent="ag_dispute", arguments={"question": "x"}, key="k-none", parent_thread_id=thread, parent_run_id=None
        )
        assert not nobody.ok and nobody.output["code"] == "specialist_not_offered", "no person, no specialist"


ASK_DISPUTE = 'call agent__ag_dispute {"question": "Can I dispute a card charge?"}'


async def called(rt: Runtime) -> list[str]:
    """The specialists that ran a turn of their own, by the agent that asked."""
    assert rt.graph_store is not None
    metas = [cast(dict[str, Any], t["meta"] or {}) for t in await rt.graph_store.threads("agent_wrapper")]
    return [f"{m['calledBy']}>{m['agentId']}" for m in metas if m.get("calledBy")]


async def grant(c: AsyncClient, holder: str, asked: str) -> None:
    """Publishes `holder` holding `agent:<asked>`, as a builder grants one agent another."""
    held: list[str] = (await c.get(f"/v1/agents/{holder}", headers=ADMIN)).json()["data"]["toolIds"]
    saved = await c.patch(f"/v1/agents/{holder}", json={"toolIds": [*held, f"agent:{asked}"]}, headers=ADMIN)
    assert saved.status_code == 200, saved.text
    body = {"version": saved.json()["data"]["version"], "note": "go"}
    live = await c.post(f"/v1/agents/{holder}/publish-requests", json=body, headers=ADMIN)
    assert live.status_code == 201 and live.json()["data"]["status"] == "approved", live.text


async def grant_dispute(c: AsyncClient) -> None:
    await grant(c, "ag_branch", "ag_dispute")


async def test_an_unattended_run_asks_no_agent_and_logs_why_while_a_persons_chat_still_does(stack: Stack) -> None:
    c, rt = stack
    await grant_dispute(c)
    job = await c.post("/v1/agents/ag_branch/jobs", json={"key": "nightly", "message": ASK_DISPUTE}, headers=ADMIN)
    assert job.status_code == 201, job.text
    assert await called(rt) == [], "a run with no person asked a specialist"
    assert rt.graph_store is not None
    with tenant_scope(TENANT):
        events = await EventLog(rt.graph_store.engine).for_threads([job.json()["data"]["threadId"]])
    refused = [e.data for e in events if e.type == "agent_call_refused"]
    assert refused == [{"agentId": "ag_branch", "withheld": ["ag_dispute"], "code": "no_caller"}], refused
    # The same agent, chatting with a person who may chat with the specialist, still asks it.
    chat = await c.post("/v1/chat/threads", json={"agentId": "ag_branch", "kbIds": []}, headers=VIEWER)
    assert chat.status_code == 201, chat.text
    await say(c, chat.json()["data"]["id"], ASK_DISPUTE, VIEWER)
    assert await called(rt) == ["ag_branch>ag_dispute"]


async def test_a_service_identity_is_offered_only_the_agents_its_scopes_reach(stack: Stack) -> None:
    c, rt = stack
    await grant_dispute(c)
    await move(rt, "ag_dispute", "")  # an agent with no team, which every team of the tenant may use
    chat = await c.post("/v1/chat/threads", json={"agentId": "ag_branch", "kbIds": []}, headers=VIEWER)
    assert chat.status_code == 201, chat.text
    thread = chat.json()["data"]["id"]

    def service(scopes: list[str]) -> Principal:
        token = Caller(
            kind="service",
            sub="scheduler",
            email="",
            name="scheduler",
            tenant_id=TENANT,
            team_id="team_ops",
            team_ids=[],
            roles={},
            scopes=scopes,
            auth_method="service",
        )
        return Principal(name="scheduler", email="", team_id="team_ops", tenant_id=TENANT, identity=token)

    calls_ = AgentCalls(rt)
    with tenant_scope(TENANT):
        with acting_for(service([])):
            assert await calls_.offers_in("ag_branch", thread) == [], "a service without chat:run asked a specialist"
        with acting_for(service(["chat:run"])):
            offered = [g.name for g in await calls_.offers_in("ag_branch", thread)]
    assert offered == ["agent__ag_dispute"], offered


async def test_a_specialist_spends_the_callers_budget_and_stops_when_it_is_spent(stack: Stack) -> None:
    c, rt = stack
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    thread = (await start(c, VIEWER))["id"]
    assert rt.usage is not None
    with tenant_scope(TENANT):
        await rt.usage.set_budget(thread, Budget(max_calls=3))
    events = await say(c, thread, ASK_DISPUTE, VIEWER)
    (first,) = [e["call"]["output"] for e in events if e.get("type") == "tool_end"]
    with tenant_scope(TENANT):
        spent = (await rt.usage.totals(thread)).calls
        # The caller's two model calls and the specialist's one, counted once, on the caller's thread.
        assert (first["status"], spent) == ("answered", 3), (first, spent)
        # The same call replayed once the budget is spent returns the answer its specialist already gave.
        assert rt.graph_store is not None
        asked = await rt.graph_store.thread_row(first["threadId"])
        assert asked is not None and asked.external_key is not None
        with acting_for(viewer()):
            again = (
                await AgentCalls(rt).run(
                    agent="ag_dispute",
                    arguments={"question": "x"},
                    key=asked.external_key.removeprefix("tool:"),
                    parent_thread_id=thread,
                    parent_run_id=None,
                )
            ).output
        assert (again["status"], again.get("threadId")) == ("answered", first["threadId"]), again
        # A second agent asked once the chain's budget is spent runs no turn; the caller is told and goes on.
        with acting_for(viewer()):
            second = (
                await AgentCalls(rt).run(
                    agent="ag_dispute",
                    arguments={"question": "x"},
                    key="k-2",
                    parent_thread_id=thread,
                    parent_run_id=None,
                )
            ).output
        assert (second["status"], second["code"]) == ("budget_reached", "chain_budget_reached"), second
        assert [step.split("@")[0] for step in second["path"]] == ["ag_branch", "ag_dispute"], second
        assert (await rt.usage.totals(thread)).calls == 3, "the stopped specialist spent from the chain"
    # The chain is the thread's team's: another team reads none of its spend.
    with scope(TENANT, "team_fraud"):
        assert (await rt.usage.totals(thread)).calls == 0, "another team read this team's chain"
    # A thread a caller links to this one in a request body spends its own budget, never this thread's.
    forged = {"calledBy": "ag_branch", "parentThreadId": thread}
    body = {"graph": "agent:ag_dispute", "externalKey": "linked", "parentThreadId": thread, "metadata": forged}
    made = await c.post("/v1/threads", json=body, headers=ADMIN)
    assert made.status_code == 201, made.text
    linked = made.json()["data"]["threadId"]
    ran = await c.post(f"/v1/threads/{linked}/runs/stream", json={"input": {"message": "Hello"}}, headers=ADMIN)
    assert ran.status_code == 200, ran.text
    assert rt.graph_store is not None
    with tenant_scope(TENANT):
        row = await rt.graph_store.thread_row(linked)
        assert row is not None and row.parent_thread_id == thread, "the body link was not stored, so nothing is proven"
        own, chain = (await rt.usage.totals(linked)).calls, (await rt.usage.totals(thread)).calls
    assert own > 0 and chain == 3, (own, chain)
    # The caller is held by the same total: its next turn waits on the budget card its person answers.
    await say(c, thread, "And the deadline?", VIEWER)
    waiting: dict[str, Any] = (await c.get(f"/v1/chat/threads/{thread}", headers=VIEWER)).json()["data"]["messages"][-1]
    card: dict[str, Any] = waiting.get("budget") or {}
    assert card.get("state") == "waiting", waiting


async def test_a_chain_record_sent_by_a_caller_is_not_the_threads_chain(stack: Stack) -> None:
    c, rt = stack
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    forged = {"startedFor": "someone@else.example", "rootThreadId": "th_x", "path": ["ag_dispute@v1"], "depth": 1}
    sent = {"chain": forged, "calledBy": "ag_dispute", "calledByName": "Someone"}
    made = await c.post("/v1/threads", json={"graph": "agent:ag_branch", "metadata": sent}, headers=ADMIN)
    assert made.status_code == 201, made.text
    thread = made.json()["data"]["threadId"]
    assert rt.graph_store is not None
    with tenant_scope(TENANT):
        kept = await rt.graph_store.thread_row(thread)
    assert kept is not None
    assert not set(sent) & set(kept.meta_object()), kept.meta_object()
    ran = await c.post(f"/v1/threads/{thread}/runs/stream", json={"input": {"message": ASK_DISPUTE}}, headers=ADMIN)
    assert ran.status_code == 200, ran.text
    assert rt.graph_store is not None
    chains = [
        cast(dict[str, Any], cast(dict[str, Any], t["meta"])["chain"])
        for t in await rt.graph_store.threads("agent_wrapper")
        if cast(dict[str, Any], t["meta"] or {}).get("calledBy")
    ]
    # Asked, though the forged record names the specialist as already on the path, and recorded from the turn itself.
    assert [(x["rootThreadId"], x["depth"], x["startedFor"] != forged["startedFor"]) for x in chains] == [
        (thread, 1, True)
    ], chains


async def test_a_handover_is_checked_like_a_start_and_back_restores_the_start_agent(stack: Stack) -> None:
    c, rt = stack
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    thread = (await start(c, VIEWER))["id"]
    url = f"/v1/chat/threads/{thread}"
    await move(rt, "ag_fraud", "team_fraud")
    refused = await c.patch(url, json={"agentId": "ag_fraud"}, headers=VIEWER)
    assert refused.status_code == 403, refused.text
    gone = await c.patch(url, json={"agentId": "ag_missing"}, headers=VIEWER)
    assert gone.status_code == 404 and gone.json()["error"]["code"] == "not_found", gone.text
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
