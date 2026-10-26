"""A step parked on outside work (c-525), on PostgreSQL with the real worker and the resume route, by failure mode: a
forged or misdirected token resumes a step; a second callback resumes it again; another team's event wakes a step; the
time limit leaves a wait row that a late event or callback still wakes; two resumes at once both run."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient, Response
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api.app import create_app
from ops_agents.api.engine_resume import resume_link, resumed
from ops_agents.api.service_events import deliver
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.events import EventLog
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.store import DefinitionStore, RunStore
from ops_engine.worker import Worker
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_service_kit.ids import new_id
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model
from tests.engine.test_lifecycle_rights import introspect, jwks
from tests.engine.test_worker import CountingTools, drain, worker


def _flow(wid: str, seconds: float) -> Any:
    return parse(
        {
            "schemaVersion": 2,
            "id": wid,
            "nodes": [
                {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
                {
                    "id": "wait",
                    "type": "ops.flow.waitFor",
                    "typeVersion": 1,
                    "name": "Wait for the core system",
                    "parameters": {"event": "extraction.finished", "key": "$.input.key", "timeoutSeconds": seconds},
                },
                {
                    "id": "done",
                    "type": "ops.flow.end",
                    "typeVersion": 1,
                    "parameters": {"outcome": "answered", "output": "$.nodes.wait.out"},
                },
                {
                    "id": "late",
                    "type": "ops.flow.end",
                    "typeVersion": 1,
                    "parameters": {"outcome": "late", "output": "$.nodes.wait.out"},
                },
            ],
            "connections": [
                {"from": {"node": "start", "port": "payload"}, "to": {"node": "wait", "port": "in"}},
                {"from": {"node": "wait", "port": "ok"}, "to": {"node": "done", "port": "in"}},
                {"from": {"node": "wait", "port": "timeout"}, "to": {"node": "late", "port": "in"}},
            ],
        }
    )


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(database_url=database_url, seed_dir=SEED)


@pytest.fixture
async def client(engine: AsyncEngine, settings: Settings) -> AsyncIterator[AsyncClient]:
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
        yield c


def _worker(engine: AsyncEngine, settings: Settings) -> Worker:
    w = worker(engine, CountingTools(), InMemorySaver())
    key = settings.review_key.get_secret_value()
    w.host.resume_link = lambda run, waiting, seconds: resume_link(
        key,
        tenant=str(run["tenant_id"]),
        team=str(run["team_id"]),
        run_id=str(run["id"]),
        waiting=waiting,
        seconds=seconds,
    )
    return w


async def _start(engine: AsyncEngine, tenant: str, team: str, seconds: float, key: str) -> str:
    flow = _flow(f"wait_{uuid4().hex[:6]}", seconds)
    tx = EngineTransactions(engine)
    with tenant_scope(tenant):
        version, _ = await DefinitionStore(tx).publish(
            flow.id,
            name="Wait",
            definition=flow.wire(),
            digest=flow.digest(),
            now="n",
            by="a@x",
            stage="live",
            team=team,
        )
        run_id = new_id("wfrun")
        await RunStore(tx).create(
            {"id": run_id, "team_id": team, "workflow_id": flow.id, "version": version, "digest": flow.digest()}
            | {"run_key": run_id, "mode": "live", "input": {"key": key}, "created_by": "a@x"}
        )
    return run_id


async def _run(engine: AsyncEngine, tenant: str, run_id: str) -> dict[str, Any]:
    with tenant_scope(tenant):
        return await RunStore(EngineTransactions(engine)).get(run_id) or {}


async def _event(engine: AsyncEngine, tenant: str, team: str, key: str) -> list[str]:
    with tenant_scope(tenant):
        out = await deliver(
            engine, None, name="extraction.finished", key=key, team_id=team, source="documents", actor=None,
            payload={"extractionId": key, "status": "done", "total": 1250},
        )  # fmt: skip
    return list(out["woke"])


async def test_a_callback_resumes_the_step_once_and_a_forged_or_misdirected_token_is_refused(
    engine: AsyncEngine, settings: Settings, client: AsyncClient
) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    run_id = await _start(engine, tenant, "team_a", 600, f"ext_{uuid4().hex[:8]}")
    w = _worker(engine, settings)
    await drain(w)
    parked = await _run(engine, tenant, run_id)
    link = parked["waiting"]["payload"]["resume"]

    async def post(url: str, token: str) -> Response:
        return await client.post(url, json={"approved": True}, headers={"Authorization": f"Bearer {token}"})

    forged = await post(link["url"], link["token"][:-4] + "AAAA")
    elsewhere = await post(link["url"].replace("/steps/wait/", "/steps/start/"), link["token"])
    real = await post(link["url"], link["token"])
    again = await post(link["url"], link["token"])
    await drain(w)
    done = await _run(engine, tenant, run_id)
    assert parked["status"] == "waiting" and link["url"] == f"/v1/runs/{run_id}/steps/wait/resume", parked
    assert (forged.status_code, elsewhere.status_code, real.status_code, again.status_code) == (401, 401, 202, 409)
    assert again.json()["error"]["code"] == "already_resumed", again.text
    assert (done["status"], done["outcome"], done["output"]) == ("succeeded", "answered", {"approved": True}), done


async def test_an_event_wakes_the_step_of_its_own_team_only(engine: AsyncEngine, settings: Settings) -> None:
    tenant, key = f"t-{uuid4().hex[:8]}", f"ext_{uuid4().hex[:8]}"
    ours = await _start(engine, tenant, "team_a", 600, key)
    theirs = await _start(engine, tenant, "team_b", 600, key)
    w = _worker(engine, settings)
    await drain(w)
    woke = await _event(engine, tenant, "team_a", key)
    await drain(w)
    mine, other = await _run(engine, tenant, ours), await _run(engine, tenant, theirs)
    assert woke == [ours], woke
    assert (mine["status"], mine["outcome"], mine["output"]["total"]) == ("succeeded", "answered", 1250), mine
    assert other["status"] == "waiting", "another team's step keeps waiting"
    with tenant_scope(tenant):
        types = [e["type"] for e in await EventLog(engine).run_events(ours, ours, 0)]
    assert "waiting_external" in types and "resumed_by_event" in types, types


async def test_the_time_limit_takes_the_timeout_way_and_a_late_event_or_callback_wakes_nothing(
    engine: AsyncEngine, settings: Settings, client: AsyncClient
) -> None:
    tenant, key = f"t-{uuid4().hex[:8]}", f"ext_{uuid4().hex[:8]}"
    run_id = await _start(engine, tenant, "team_a", 1, key)
    w = _worker(engine, settings)
    await drain(w)
    link = (await _run(engine, tenant, run_id))["waiting"]["payload"]["resume"]
    await asyncio.sleep(1.5)
    await drain(w)
    timed_out = await _run(engine, tenant, run_id)
    with tenant_scope(tenant):
        left = await RunStore(EngineTransactions(engine)).waits_for("extraction.finished", key)
    woke = await _event(engine, tenant, "team_a", key)
    late = await client.post(link["url"], json={"approved": True}, headers={"Authorization": f"Bearer {link['token']}"})
    assert (timed_out["status"], timed_out["outcome"]) == ("succeeded", "late"), timed_out
    assert timed_out["output"] == {"waitedFor": "extraction.finished", "key": key, "seconds": 1.0}, timed_out
    assert left == [], "the time limit clears the step's wait row"
    assert woke == [] and late.status_code == 409, (woke, late.status_code)


async def test_two_resumes_of_one_pause_run_it_once_and_record_the_second_as_ignored(
    engine: AsyncEngine, settings: Settings
) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    run_id = await _start(engine, tenant, "team_a", 600, f"ext_{uuid4().hex[:8]}")
    await drain(_worker(engine, settings))
    run = await _run(engine, tenant, run_id)
    with tenant_scope(tenant):
        first = await resumed(engine, run, run["waiting"], {"callback": {"n": 1}}, source="callback")
        second = await resumed(engine, run, run["waiting"], {"event": {"n": 2}}, source="event")
        types = [e["type"] for e in await EventLog(engine).run_events(run_id, run_id, 0)]
    assert (first, second) == (True, False)
    assert types.count("resumed_by_callback") == 1 and "resume_ignored" in types, types
