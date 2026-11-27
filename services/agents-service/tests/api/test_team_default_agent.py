"""A team's default agent, its specialists and the @mention handover, by failure mode: someone other than a
team admin changes the default; a chat starts on no default, a default that is not live or another team's agent; the
default agent asks a specialist the person may not chat with, or reaches it by naming the tool; a specialist runs
without the person, or asks another agent; a handover to an agent the person may not chat with or one not live; Back
returns to the wrong agent, or a reload loses who answered. Tokens carry roles as platform-service mints them."""

from __future__ import annotations

import json
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
from ops_agents.api.child_runs import ChildRuns, acting_for
from ops_agents.api.deps import Runtime
from ops_agents.api.ops_tools import ops_assistant_id
from ops_agents.api.run_person import person_of_thread
from ops_agents.graphs.common import Asker
from ops_agents.store.agent_registry import registry_agents
from ops_agents.store.base import metadata
from ops_agents.store.events import EventLog
from ops_agents.store.tenancy import LOCAL_TENANT, tenant_scope
from ops_agents.store.workflow_registry import registry_workflows
from ops_contracts import chain
from ops_engine.store import metadata as engine_metadata
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_identity import Principal as Caller
from ops_metering import Budget
from ops_service_kit.settings import Settings
from ops_store.isolation import scope
from tests.api.test_action_roles import ADMIN, OUTSIDER, REVIEWER, VIEWER, introspect
from tests.conftest import SEED, FakeGraphModels, empty_engine, fixture_knowledge, scripted_model, sse_events
from tests.engine.test_lifecycle_rights import TENANT, jwks, person
from tests.model_gateway import through_gateway
from tests.saves import save_agent

URL = "/v1/chat/default-agent"
EMAIL: dict[str, Any] = {"sender": "a@b.example", "subject": "Dispute", "body": "I did not make this payment."}
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


@pytest.fixture
async def budget_stack(database_url: str) -> AsyncIterator[Stack]:
    """`stack` with its model calls through the model gateway, which holds the chain's budget."""
    settings = Settings(database_url=database_url, seed_dir=SEED)
    auth = Auth(
        Identity(audience="agents", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="agents", verifiers=service_verifiers(settings, "agents"), scopes=settings.service_scopes),
    )
    async with empty_engine(database_url) as engine, through_gateway(engine, FakeGraphModels(), auth=auth) as g:
        yield g.client, g.runtime


def live(rt: Runtime, agent_id: str) -> Asker:
    """The agent as a turn on its published version runs it."""
    a = rt.catalog.agent(agent_id)
    assert a is not None, agent_id
    return Asker.of(a.id, a.version, list(a.tools))


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
        for t in [r.model_dump() for r in await rt.graph_store.thread_rows("agent_wrapper")]
        if cast(dict[str, Any], t["meta"] or {}).get("calledBy")
    ]
    assert [(t["meta"]["agentId"], t["meta"]["calledBy"], t["meta"]["startedFor"]) for t in children] == [
        ("ag_dispute", "ag_branch", "vera@harborpine.example")
    ], "the specialist ran its own turn, for the person"
    calls_ = AgentCalls(rt)
    with tenant_scope(TENANT):
        with acting_for(viewer()):
            offered = {g.name for g in await calls_.offers_in(live(rt, "ag_branch"), thread)}
            assert "agent__ag_dispute" in offered and "agent__ag_fraud" not in offered, offered
            named = await calls_.run(
                asker=live(rt, "ag_branch"),
                agent="ag_fraud",
                arguments={"question": "x"},
                key="k-fraud",
                parent_thread_id=thread,
                parent_run_id=None,
            )
            assert not named.ok and named.output["code"] == "specialist_not_offered", named.output
            assert await calls_.offers_in(live(rt, "ag_branch"), children[0]["id"]) == [], (
                "a specialist asks no other agent"
            )
            assert await calls_.offers_in(live(rt, "ag_dispute"), thread) == [], (
                "only the team default asks specialists"
            )
        nobody = await calls_.run(
            asker=live(rt, "ag_branch"),
            agent="ag_dispute",
            arguments={"question": "x"},
            key="k-none",
            parent_thread_id=thread,
            parent_run_id=None,
        )
        assert not nobody.ok and nobody.output["code"] == "specialist_not_offered", "no person, no specialist"


ASK_DISPUTE = 'call agent__ag_dispute {"question": "Can I dispute a card charge?"}'


async def called(rt: Runtime) -> list[str]:
    """The specialists that ran a turn of their own, by the agent that asked."""
    assert rt.graph_store is not None
    metas = [t.meta_object() for t in await rt.graph_store.thread_rows("agent_wrapper")]
    return [f"{m['calledBy']}>{m['agentId']}" for m in metas if m.get("calledBy")]


async def grant(c: AsyncClient, holder: str, asked: str) -> None:
    """Publishes `holder` holding `agent:<asked>`, as a builder grants one agent another."""
    held: list[str] = (await c.get(f"/v1/agents/{holder}", headers=ADMIN)).json()["data"]["toolIds"]
    saved = await save_agent(c, holder, {"toolIds": [*held, f"agent:{asked}"]}, headers=ADMIN)
    assert saved.status_code == 200, saved.text
    body = {"version": saved.json()["data"]["version"], "note": "go"}
    live = await c.post(f"/v1/agents/{holder}/publish-requests", json=body, headers=ADMIN)
    assert live.status_code == 201 and live.json()["data"]["status"] == "approved", live.text


async def grant_dispute(c: AsyncClient) -> None:
    await grant(c, "ag_branch", "ag_dispute")


def ask(agent: str, question: str) -> str:
    """What makes the scripted model ask `agent` the question, which may itself ask another agent."""
    return f"call agent__{agent} {json.dumps({'question': question})}"


async def test_an_agent_already_on_the_chain_is_not_asked_again(stack: Stack, monkeypatch: pytest.MonkeyPatch) -> None:
    c, rt = stack
    # Chains two calls deep, so an asked agent may ask on, and two agents granted each other.
    monkeypatch.setattr(chain, "MAX_DEPTH", 2)
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    await grant(c, "ag_dispute", "ag_branch")
    await grant(c, "ag_dispute", "ag_fraud")
    thread = (await start(c, VIEWER))["id"]
    # The asked agent asks one not on the chain, which answers: nothing but the path refuses the call back below.
    await say(c, thread, ask("ag_dispute", ask("ag_fraud", "Is this card blocked?")), VIEWER)
    assert await called(rt) == ["ag_branch>ag_dispute", "ag_dispute>ag_fraud"]
    # The asked agent told to ask the one that asked it: not offered, so it is not called.
    await say(c, thread, ask("ag_dispute", ask("ag_branch", "And you?")), VIEWER)
    assert sorted(await called(rt)) == ["ag_branch>ag_dispute", "ag_branch>ag_dispute", "ag_dispute>ag_fraud"]
    assert rt.graph_store is not None
    threads = [
        (str(t["id"]), cast(dict[str, Any], t["meta"] or {}))
        for t in [r.model_dump() for r in await rt.graph_store.thread_rows("agent_wrapper")]
    ]
    deepest = next(m for _, m in threads if m.get("calledBy") == "ag_dispute")["chain"]
    assert ([s.split("@")[0] for s in deepest["path"]], deepest["depth"], deepest["rootThreadId"]) == (
        ["ag_branch", "ag_dispute", "ag_fraud"],
        2,
        thread,
    ), deepest
    # A model that names the tool it was not offered is refused by the same rule, and told why.
    second = next(tid for tid, m in threads if m.get("calledBy") == "ag_branch")
    with tenant_scope(TENANT), acting_for(viewer()):
        looped = await AgentCalls(rt).run(
            asker=live(rt, "ag_dispute"),
            agent="ag_branch",
            arguments={"question": "x"},
            key="k-loop",
            parent_thread_id=second,
            parent_run_id=None,
        )
    assert not looped.ok and looped.output["code"] == "agent_on_path", looped.output


async def test_an_asked_agent_asks_no_one_at_the_default_depth(stack: Stack) -> None:
    c, rt = stack
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    # Granted, in the person's team and not on the path: only the chain's depth keeps the asked agent from asking it.
    await grant(c, "ag_dispute", "ag_fraud")
    thread = (await start(c, VIEWER))["id"]
    await say(c, thread, ask("ag_dispute", ask("ag_fraud", "Is this card blocked?")), VIEWER)
    assert await called(rt) == ["ag_branch>ag_dispute"], "a chain went deeper than one call"
    assert rt.graph_store is not None
    (asked,) = [r.id for r in await rt.graph_store.thread_rows("agent_wrapper") if r.meta_object().get("calledBy")]
    with tenant_scope(TENANT), acting_for(viewer()):
        deeper = await AgentCalls(rt).run(
            asker=live(rt, "ag_dispute"),
            agent="ag_fraud",
            arguments={"question": "x"},
            key="k-deep",
            parent_thread_id=asked,
            parent_run_id=None,
        )
    assert not deeper.ok and deeper.output["code"] == "chain_too_deep", deeper.output


async def test_a_guarded_agent_asked_at_the_cap_makes_no_model_call_for_its_guardrail_check(
    budget_stack: Stack,
) -> None:
    c, rt = budget_stack
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    rule = {"name": "No investment advice", "topics": ["investment advice"], "message": "I can't advise on that."}
    made = await c.post("/v1/guardrails", json=rule, headers=ADMIN)
    assert made.status_code == 201, made.text
    gid = made.json()["data"]["id"]
    live = await c.post(f"/v1/guardrails/{gid}/publish-requests", json={"version": 1}, headers=ADMIN)
    assert live.status_code == 201, live.text
    pins = {"guardrailPins": [{"guardrailId": gid, "version": 1}]}
    saved = await save_agent(c, "ag_dispute", pins, headers=ADMIN)
    assert saved.status_code == 200, saved.text
    body = {"version": saved.json()["data"]["version"], "note": "go"}
    assert (await c.post("/v1/agents/ag_dispute/publish-requests", json=body, headers=ADMIN)).status_code == 201
    thread = (await start(c, VIEWER))["id"]
    assert rt.usage is not None
    with tenant_scope(TENANT):
        await rt.usage.set_budget(thread, Budget(max_calls=1))
    events = await say(c, thread, ASK_DISPUTE, VIEWER)
    (asked,) = [e["call"]["output"] for e in events if e.get("type") == "tool_end"]
    with tenant_scope(TENANT):
        spent = (await rt.usage.totals(asked["threadId"])).calls
    # Its first model call is the check of the question against its guardrail, which is not streamed: refused at the
    # cap like any other, and the turn ends for the budget, not as a guardrail outage.
    assert (asked["status"], asked.get("code"), spent) == ("budget_reached", "chain_budget_reached", 0), asked


async def test_an_asked_agents_chain_is_the_same_after_an_approval_pause(budget_stack: Stack) -> None:
    c, rt = budget_stack
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    thread = (await start(c, VIEWER))["id"]
    events = await say(c, thread, ask("ag_fraud", "Place a 24-hour hold on wire W-88213"), VIEWER)
    (asked,) = [e["call"]["output"] for e in events if e.get("type") == "tool_end"]
    assert asked["status"] == "waiting_review", asked
    assert rt.graph_store is not None and rt.usage is not None
    with tenant_scope(TENANT):
        before = await rt.graph_store.thread_row(asked["threadId"])
        spent = (await rt.usage.totals(thread)).calls
    assert before is not None
    decision = {"decision": "rejected", "reason": "Not this wire."}
    ran = await c.post(f"/reviews/{asked['threadId']}/decision", json=decision, headers=REVIEWER)
    assert ran.status_code == 200, ran.text
    with tenant_scope(TENANT):
        after = await rt.graph_store.thread_row(asked["threadId"])
        chain = cast(dict[str, Any], after.meta_object()["chain"]) if after is not None else {}
        assert chain == before.meta_object()["chain"] and chain["rootThreadId"] == thread, chain
        # The resumed turn's model call is spent from the conversation the chain started on.
        assert (await rt.usage.totals(thread)).calls > spent
        with acting_for(viewer()):
            assert await AgentCalls(rt).offers_in(live(rt, "ag_fraud"), asked["threadId"]) == []


async def test_a_run_with_no_person_reaches_only_its_own_teams_agents_and_workflows(stack: Stack) -> None:
    c, rt = stack

    async def scheduled(key: str, asked: str) -> str:
        """A scheduled run of Branch Concierge told to ask `asked`; its thread."""
        body = {"key": key, "message": ask(asked, "Anything held?")}
        made = await c.post("/v1/agents/ag_branch/jobs", json=body, headers=ADMIN)
        assert made.status_code == 201, made.text
        return str(made.json()["data"]["threadId"])

    # The team's default agent, which a person's chat lets ask every specialist: a run with no person does not.
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    await grant(c, "ag_branch", "ag_dispute")
    await scheduled("nightly", "ag_dispute")
    await scheduled("monthly", "ag_fraud")  # in its own team, and never granted to it
    await grant(c, "ag_branch", "ag_fraud")
    await move(rt, "ag_fraud", "team_fraud")
    job = {"threadId": await scheduled("weekly", "ag_fraud")}  # granted, and now another team's
    # A scheduled run acts as its agent: it asks the agent it was granted in its own team, and no other.
    assert await called(rt) == ["ag_branch>ag_dispute"]
    assert rt.graph_store is not None
    rows = [r.model_dump() for r in await rt.graph_store.thread_rows("agent_wrapper")]
    (asked_row,) = [t for t in rows if cast(dict[str, Any], t["meta"] or {}).get("calledBy")]
    asked_meta = cast(dict[str, Any], asked_row["meta"])
    assert asked_meta["chain"]["startedFor"] == "agent:ag_branch", asked_meta
    # The asked agent acts as the run that asked it, not as a chat that lost its person, whose calls are refused.
    assert person_of_thread(asked_row) is None
    with tenant_scope(TENANT):
        events = await EventLog(rt.graph_store.engine).for_threads([job["threadId"]])
        refused = [e.data for e in events if e.type == "agent_call_refused"]
        assert refused == [{"agentId": "ag_branch", "withheld": ["ag_fraud"], "code": "other_team"}], refused
        # The same rule for a workflow it starts: its own team's, never another team's.
        runs = ChildRuns(rt)
        mine = await runs.run(
            workflow="dispute_email", arguments=EMAIL, key="k-own", parent_thread_id=job["threadId"], parent_run_id=None
        )
        assert mine.ok, mine.output
        async with rt.db.begin() as conn:
            await conn.execute(registry_workflows.update().values(team_id="team_fraud"))
        theirs = await runs.run(
            workflow="dispute_email",
            arguments=EMAIL,
            key="k-other",
            parent_thread_id=job["threadId"],
            parent_run_id=None,
        )
        assert not theirs.ok and theirs.output["code"] == "other_team", theirs.output
        # A person's chat turn resumed with no person known still asks no one.
        chat = await c.post("/v1/chat/threads", json={"agentId": "ag_branch", "kbIds": []}, headers=VIEWER)
        assert chat.status_code == 201, chat.text
        assert await AgentCalls(rt).offers_in(live(rt, "ag_branch"), chat.json()["data"]["id"]) == []


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
            assert await calls_.offers_in(live(rt, "ag_branch"), thread) == [], (
                "a service without chat:run asked a specialist"
            )
        with acting_for(service(["chat:run"])):
            offered = [g.name for g in await calls_.offers_in(live(rt, "ag_branch"), thread)]
    assert offered == ["agent__ag_dispute"], offered


async def test_a_specialist_spends_the_callers_budget_and_stops_when_it_is_spent(budget_stack: Stack) -> None:
    c, rt = budget_stack
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
                    asker=live(rt, "ag_branch"),
                    agent="ag_dispute",
                    arguments={"question": "x"},
                    key=asked.external_key.removeprefix("tool:"),
                    parent_thread_id=thread,
                    parent_run_id=None,
                )
            ).output
        assert (again["status"], again.get("threadId")) == ("answered", first["threadId"]), again
        # A second agent asked once the chain's budget is spent makes no model call; the caller is told and goes on.
        with acting_for(viewer()):
            second = (
                await AgentCalls(rt).run(
                    asker=live(rt, "ag_branch"),
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
    # No request body links a thread to this one: the field is refused, a copy in the metadata is dropped, and the
    # thread a caller makes spends its own budget, never this thread's.
    forged = {"calledBy": "ag_branch", "parentThreadId": thread}
    body = {"graph": "agent:ag_dispute", "externalKey": "linked", "metadata": forged}
    refused = await c.post("/v1/threads", json=body | {"parentThreadId": thread}, headers=ADMIN)
    assert refused.status_code == 400, refused.text
    made = await c.post("/v1/threads", json=body, headers=ADMIN)
    assert made.status_code == 201, made.text
    linked = made.json()["data"]["threadId"]
    ran = await c.post(f"/v1/threads/{linked}/runs/stream", json={"input": {"message": "Hello"}}, headers=ADMIN)
    assert ran.status_code == 200, ran.text
    assert rt.graph_store is not None
    with tenant_scope(TENANT):
        row = await rt.graph_store.thread_row(linked)
        assert row is not None and row.parent_thread_id is None and not set(forged) & set(row.meta_object()), row
        own, chain = (await rt.usage.totals(linked)).calls, (await rt.usage.totals(thread)).calls
    assert own > 0 and chain == 3, (own, chain)
    # The caller is held by the same total: its next turn waits on the budget card its person answers.
    await say(c, thread, "And the deadline?", VIEWER)
    waiting: dict[str, Any] = (await c.get(f"/v1/chat/threads/{thread}", headers=VIEWER)).json()["data"]["messages"][-1]
    card: dict[str, Any] = waiting.get("budget") or {}
    assert card.get("state") == "waiting", waiting


async def test_a_specialist_makes_no_model_call_past_the_chains_budget_and_the_asking_agent_closes_once(
    budget_stack: Stack,
) -> None:
    c, rt = budget_stack
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    thread = (await start(c, VIEWER))["id"]
    assert rt.usage is not None
    with tenant_scope(TENANT):
        # Spent by the asking agent's first model call, before the specialist it asks has made one.
        await rt.usage.set_budget(thread, Budget(max_calls=1))
    events = await say(c, thread, ASK_DISPUTE, VIEWER)
    (asked,) = [e["call"]["output"] for e in events if e.get("type") == "tool_end"]
    with tenant_scope(TENANT):
        specialist, whole = (await rt.usage.totals(asked["threadId"])).calls, (await rt.usage.totals(thread)).calls
    assert (asked["status"], asked.get("code"), specialist) == ("budget_reached", "chain_budget_reached", 0), asked
    # One call past the cap, on the thread the chain started on: the asking agent's closing answer.
    assert whole == 2, whole
    url = f"/v1/chat/threads/{thread}"
    closing: dict[str, Any] = (await c.get(url, headers=VIEWER)).json()["data"]["messages"][-1]
    assert closing["role"] == "assistant" and closing["content"] and "budget" not in closing["content"], closing
    # Its next turn waits on the budget card, which its person answers.
    await say(c, thread, "And the deadline?", VIEWER)
    waiting: dict[str, Any] = (await c.get(url, headers=VIEWER)).json()["data"]["messages"][-1]
    card: dict[str, Any] = waiting.get("budget") or {}
    assert card.get("state") == "waiting", waiting
    with tenant_scope(TENANT):
        assert (await rt.usage.totals(thread)).calls == 2, "a model call ran while the thread waited on its budget"


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
        for t in [r.model_dump() for r in await rt.graph_store.thread_rows("agent_wrapper")]
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
