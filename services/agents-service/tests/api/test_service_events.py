"""A service event starts its handler workflow (c-258), by failure mode: a repeat delivery starts a second run; a run
that failed is never tried again, or is retried under a new key; an event nobody handles is lost; a team's own workflow
with the Service event trigger, or under the handler's id, reacts to events; the handler cannot be edited through
review or run by hand like any workflow; a token without events:emit, a person's token or an oversized payload is
accepted; a service reports another service's event, or for a team its token does not name; the asker of a request is
lost, or the reporting service is."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_access import Grant
from ops_access.check import DEFAULT
from ops_agents.api.app import create_app
from ops_agents.api.deps import Runtime
from ops_agents.store.base import metadata
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.store import DefinitionStore
from ops_engine.store import metadata as engine_metadata
from ops_engine.store.tables import engine_runs
from ops_identity import Auth, Identity, ServiceAuth, dev_service_signer, mint_service_token, service_verifiers
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import mint
from ops_service_kit.settings import Settings
from tests.api.test_action_roles import introspect
from tests.api.test_team_default_agent import Stack, jwks
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model
from tests.engine.test_lifecycle_rights import BUILDER, PLATFORM, TENANT

EVENT = "file.deleted"


@pytest.fixture
async def stack() -> AsyncIterator[Stack]:
    """Platform people as in test_team_default_agent, and service tokens capped by the deployed scope allowlist."""
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


def event_workflow(wid: str = "sys_file_deleted", event: str = EVENT) -> dict[str, Any]:
    def node(nid: str, kind: str, **params: Any) -> dict[str, Any]:
        return {"id": nid, "type": kind, "typeVersion": 1, "name": nid.capitalize(), "parameters": params}

    return {
        "schemaVersion": 2,
        "id": wid,
        "name": "Purge a deleted file's records",
        "nodes": [
            node("start", "ops.trigger.event", event=event),
            node("done", "ops.flow.end", outcome="purged", output="$.input.fileId"),
        ],
        "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
    }


def service(
    scopes: tuple[str, ...] = ("events:emit",), name: str = "files", team: str | None = "team_ops"
) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service=name, audience="agents", tenant_id=TENANT, scopes=list(scopes), team_id=team
    )
    return {"Authorization": f"Bearer {token}"}


async def emit(c: AsyncClient, key: str, *, name: str = EVENT, status: int = 202, **more: Any) -> dict[str, Any]:
    body = {"name": name, "key": key, "teamId": "team_ops", "payload": {"fileId": key}} | more
    r = await c.post("/v1/events", json=body, headers=service())
    assert r.status_code == status, r.text
    return r.json()["data"] if status == 202 else r.json()["error"]


async def run(c: AsyncClient, run_id: str) -> dict[str, Any]:
    r = await c.get(f"/v1/runs/{run_id}", headers=BUILDER)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_one_event_starts_one_run_and_a_failed_one_is_retried_by_key(stack: Stack) -> None:
    c, rt = stack
    rt.event_workflows = [event_workflow()]
    first = await emit(c, "fil_1")
    again = await emit(c, "fil_1")
    assert first["status"] == "started" and first["runIds"] == again["runIds"] and again["attempts"] == 1, again
    [run_id] = first["runIds"]
    detail = await run(c, run_id)
    assert detail["startedBy"] == {"kind": "event", "id": "files/file.deleted", "name": "file.deleted from files"}
    async with rt.db.begin() as conn:
        await conn.execute(engine_runs.update().where(engine_runs.c.id == run_id).values(status="failed"))
    retried = await emit(c, "fil_1")
    assert retried["attempts"] == 2 and retried["runIds"] != [run_id], retried
    async with rt.db.connect() as conn:
        keys = {r.run_key for r in await conn.execute(sa.select(engine_runs.c.run_key))}
    assert {"file.deleted:fil_1", "file.deleted:fil_1:2"} <= keys, keys


async def test_an_event_nobody_listens_to_is_recorded_unhandled(stack: Stack) -> None:
    c, rt = stack
    rt.event_workflows = [event_workflow()]
    got = await emit(c, "k1", name="file.archived")
    assert (got["status"], got["runIds"]) == ("unhandled", []), got


async def test_a_team_workflow_with_the_trigger_never_reacts(stack: Stack) -> None:
    c, rt = stack
    rt.event_workflows = []
    mine = event_workflow("ops_listener")
    saved = await c.post("/v1/workflows/definitions", json={"definition": mine}, headers=BUILDER)
    assert saved.status_code == 201, saved.text
    live = await c.post("/v1/workflows/definitions/ops_listener/publish-requests", json={}, headers=BUILDER)
    assert live.status_code == 201, live.text
    assert (await emit(c, "fil_2"))["status"] == "unhandled", "a team workflow heard a service event"


async def test_the_handler_is_edited_through_review_and_run_by_hand_like_any_shared_workflow(stack: Stack) -> None:
    # No team owns it; the roles grid decides in the acting team, so a builder edits and runs it like any workflow.
    c, rt = stack
    rt.event_workflows = [event_workflow()]
    await emit(c, "fil_3")
    rt.settings = rt.settings.model_copy(update={"registry_auto_approve": False})
    changed = event_workflow()
    changed["nodes"][1]["parameters"]["outcome"] = "purged_and_logged"  # a step changed: a major change
    saved = await c.post("/v1/workflows/definitions", json={"definition": changed}, headers=BUILDER)
    asked = await c.post("/v1/workflows/definitions/sys_file_deleted/publish-requests", json={}, headers=BUILDER)
    shown = (await c.get("/v1/workflows/definitions/sys_file_deleted", headers=BUILDER)).json()["data"]
    assert (saved.status_code, asked.status_code) == (201, 201), (saved.text, asked.text)
    assert asked.json()["data"]["status"] == "pending", asked.text
    assert (shown["version"], shown["liveVersion"]) == (2, 1), "the edit waits for its review; v1 still handles events"
    run = await c.post(
        "/v1/runs",
        json={"workflowId": "sys_file_deleted", "mode": "live", "input": {"fileId": "fil_9"}},
        headers=BUILDER,
    )
    assert run.status_code == 202, run.text


async def test_only_a_service_with_the_scope_reports_an_event(stack: Stack) -> None:
    c, rt = stack
    rt.event_workflows = [event_workflow()]
    body: dict[str, Any] = {"name": EVENT, "key": "k", "teamId": "team_ops", "payload": {}}
    bare = await c.post("/v1/events", json=body, headers=service(scopes=()))
    person = await c.post("/v1/events", json=body, headers=BUILDER)
    assert (bare.status_code, bare.json()["error"]["code"]) == (403, "scope_required"), bare.text
    assert person.status_code in (401, 403), person.text
    big = await emit(c, "k", status=422, payload={"blob": "x" * 20_000})
    assert big["code"] == "payload_too_large"


async def test_a_request_is_the_askers_run_and_says_which_service_carried_it(stack: Stack) -> None:
    c, rt = stack
    rt.event_workflows = [event_workflow()]
    [run_id] = (await emit(c, "fil_4", actor="james@northfield.example"))["runIds"]
    started = (await run(c, run_id))["startedBy"]
    assert (started["kind"], started["id"]) == ("person", "james@northfield.example"), started
    assert started["via"] == {"kind": "event", "id": "files/file.deleted", "name": "file.deleted from files"}
    # created_by is the asker's own email, so every rule on who started a run (decide, cancel) reads the person.
    async with rt.db.connect() as conn:
        row = (await conn.execute(sa.select(engine_runs).where(engine_runs.c.id == run_id))).mappings().one()
    assert (row["created_by"], row["started_via"]) == ("james@northfield.example", "event:files/file.deleted"), row


async def test_an_id_a_team_already_holds_is_skipped_not_failed_on_every_event(stack: Stack) -> None:
    c, rt = stack
    rt.event_workflows = [event_workflow(), event_workflow("sys_file_archived", event="file.archived")]
    taken = parse(event_workflow())
    with tenant_scope(TENANT):
        await DefinitionStore(EngineTransactions(rt.db)).publish(
            taken.id, name="Squatted", definition=taken.wire(), digest="s" * 64, now="n", by="b@x", team="team_ops"
        )
    # A team's workflow under the handler's id never handles the event; the other events are still handled.
    assert (await emit(c, "fil_5"))["status"] == "unhandled"
    assert (await emit(c, "fil_5", name="file.archived"))["status"] == "started"


async def test_a_service_reports_its_own_events_for_the_team_its_token_names(stack: Stack) -> None:
    c, rt = stack
    rt.event_workflows = [event_workflow()]
    body: dict[str, Any] = {"name": EVENT, "key": "k", "teamId": "team_ops", "payload": {}}
    tools = await c.post("/v1/events", json=body, headers=service(name="tools"))
    assert (tools.status_code, tools.json()["error"]["code"]) == (403, "event_not_owned"), tools.text
    other_team = await c.post("/v1/events", json=body, headers=service(team="team_fraud"))
    no_team = await c.post("/v1/events", json=body, headers=service(team=None))
    for r in (other_team, no_team):
        assert (r.status_code, r.json()["error"]["code"]) == (403, "team_mismatch"), r.text
    asked = {**body, "name": "tool_access.requested", "actor": "james@northfield.example"}
    files = await c.post("/v1/events", json=asked, headers=service())
    assert (files.status_code, files.json()["error"]["code"]) == (403, "event_not_owned"), files.text
    assert (await c.post("/v1/events", json=body, headers=service())).status_code == 202


async def test_a_role_without_workflows_edit_cannot_change_the_handler(stack: Stack) -> None:
    c, rt = stack
    rt.event_workflows = [event_workflow()]
    await emit(c, "fil_10")
    grants: tuple[Grant, ...] = tuple(("workflows", a, "all") for a in ("view", "run"))
    DEFAULT.grids._cache[TENANT] = (PERM_VERSION, {RUNNER_ROLE: grants})  # pyright: ignore[reportPrivateUsage]
    try:
        changed = event_workflow()
        changed["nodes"][1]["parameters"]["outcome"] = "purged_quietly"
        saved = await c.post("/v1/workflows/definitions", json={"definition": changed}, headers=runner())
        assert (saved.status_code, saved.json()["error"]["code"]) == (403, "role_required"), saved.text
    finally:
        DEFAULT.grids._cache.pop(TENANT, None)  # pyright: ignore[reportPrivateUsage]


RUNNER_ROLE, PERM_VERSION = "workflow_runner", 311


def runner() -> dict[str, str]:
    """A custom role whose grid has workflows.view and run but not edit, as platform-service would serve it."""
    claims = {
        "sub": "rae",
        "email": "rae@northfield.example",
        "name": "rae",
        "kind": "person",
        "aud": ["agents"],
        "tenant_id": TENANT,
        "team_ids": ["team_ops"],
        "access": {"team_ops": [RUNNER_ROLE]},
        "perm_version": PERM_VERSION,
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": "team_ops"}
