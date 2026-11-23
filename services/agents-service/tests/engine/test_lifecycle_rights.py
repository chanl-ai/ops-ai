"""Who may publish, pause or resume a v2 workflow, by failure mode: a builder pausing a workflow no team owns (the
seed's, which every team runs), and someone outside the builder and admin roles taking a team's workflow live."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from ops_access import AREAS, BUILTIN_GRIDS, encode_grid
from ops_agents.api.app import create_app
from ops_agents.api.routers.engine import router as engine_router
from ops_agents.store.base import metadata
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import DefinitionStore
from ops_engine.store import metadata as engine_metadata
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import Ed25519Signer, mint
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model
from tests.engine.test_lifecycle import definition

PLATFORM = Ed25519Signer.generate("platform-test")
# The dev seed's tenant: the seeded agents these callers chat with are its (an agent id is held by one tenant).
TENANT = "local"


def person(
    sub: str,
    team: str,
    role: str,
    *,
    policies: dict[str, Any] | None = None,
    unticked: tuple[tuple[str, str], ...] = (),
) -> dict[str, str]:
    """A platform token for `role` in `team`. `unticked` names cells an admin took off the role on the Roles page: the
    token then carries the role's stored grid without them, as platform-service issues it after that edit."""
    claims: dict[str, Any] = {
        "sub": sub,
        "email": f"{sub}@harborpine.example",
        "name": sub,
        "kind": "person",
        "security_team": "team_security",
        "aud": ["agents"],
        "tenant_id": TENANT,
        "team_ids": [team],
        "roles": {team: role},
        **({"policies": policies} if policies is not None else {}),
    }
    if unticked:
        kept = [g for g in BUILTIN_GRIDS[role] if (g[0], g[1]) not in set(unticked)]
        claims |= {"access": {team: [role]}, "grids": {role: encode_grid(kept)}}
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": team}


BUILDER = person("james", "team_ops", "builder")
# A builder whose role an admin took every manage cell off: edits definitions, never a system record.
NO_MANAGE = tuple((area, "manage") for area in AREAS)
BUILDER_WITHOUT_MANAGE = person("jo", "team_ops", "builder", unticked=NO_MANAGE)
# A builder whose role an admin took the workflows publish cell off: saves changes, never publishes them.
BUILDER_WITHOUT_PUBLISH = person("bo", "team_ops", "builder", unticked=(("workflows", "publish"),))
ADMIN = person("priya", "team_ops", "admin")
VIEWER = person("vera", "team_ops", "viewer")
# A viewer whose role an admin took the workflows view cell off.
NOT_A_WORKFLOW_READER = person("wes", "team_ops", "viewer", unticked=(("workflows", "view"),))
# A member who only chats: no workflows cell at all.
CHAT_USER = person("cora", "team_ops", "chat_user")


async def jwks() -> dict[str, Any]:
    return {"keys": [PLATFORM.public_jwk()]}


async def introspect(_key: str) -> dict[str, Any] | None:
    return None


@pytest.fixture
async def stack() -> AsyncIterator[tuple[AsyncClient, AsyncEngine]]:
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
        yield c, engine


async def unowned_live(engine: AsyncEngine, wid: str, *, by: str) -> None:
    """A workflow stored with no team, as the dev seed stores its workflows, and live."""
    store = DefinitionStore(EngineTransactions(engine))
    d = definition(wid)
    with tenant_scope(TENANT):
        version, _ = await store.publish(wid, name="Seeded", definition=d, digest=wid.ljust(64, "s"), now="n", by=by)
        await store.go_live(wid, version)


async def test_a_workflow_no_team_owns_is_paused_by_whoever_the_grid_lets_edit(
    stack: tuple[AsyncClient, AsyncEngine],
) -> None:
    # The roles grid decides in the acting team, as for a team's own workflow: builders and admins edit, viewers do not.
    c, engine = stack
    await unowned_live(engine, "seeded_refunds", by="seed")
    refused = await c.post("/v1/workflows/definitions/seeded_refunds/pause", headers=VIEWER)
    assert refused.status_code == 403, refused.text
    assert (await c.post("/v1/workflows/definitions/seeded_refunds/pause", headers=BUILDER)).status_code == 200


async def test_a_team_workflow_is_published_by_its_builders_and_admins_only(
    stack: tuple[AsyncClient, AsyncEngine],
) -> None:
    c, _ = stack
    saved = await c.post("/v1/workflows/definitions", json={"definition": definition("ops_refunds")}, headers=BUILDER)
    assert saved.status_code == 201, saved.text
    refused = await c.post("/v1/workflows/definitions/ops_refunds/publish-requests", json={}, headers=VIEWER)
    assert refused.status_code == 403, refused.text
    # The one-call publish of a working copy asks the publish right before it makes the version.
    wf = "/v1/workflows/definitions/ops_refunds"
    base = (await c.get(wf, headers=BUILDER)).json()["data"]["saveBase"]
    body = {"definition": definition("ops_refunds") | {"name": "Unpublished"}}
    body |= {"baseVersion": base["version"], "baseDigest": base["digest"]}
    copy_base = (await c.put(f"{wf}/working-copy", json=body, headers=BUILDER)).json()["data"]["saveBase"]
    one_call = {"baseVersion": copy_base["version"], "baseDigest": copy_base["digest"]}
    refused = await c.post(f"{wf}/publish-requests", json=one_call, headers=BUILDER_WITHOUT_PUBLISH)
    assert refused.status_code == 403, refused.text
    after = (await c.get(wf, headers=BUILDER)).json()["data"]
    assert [v["version"] for v in after["versions"]] == [1] and after["workingCopy"] is not None, after
    asked = await c.post(f"{wf}/publish-requests", json=one_call, headers=BUILDER)
    assert asked.status_code == 201, asked.text


async def test_a_member_without_the_workflows_view_cell_reads_no_workflow_definition(
    stack: tuple[AsyncClient, AsyncEngine],
) -> None:
    # Every GET under /v1/workflows/definitions, taken from the router: a route added without the view check fails here.
    c, _ = stack
    wf = "/v1/workflows/definitions/ops_refunds"
    saved = await c.post("/v1/workflows/definitions", json={"definition": definition("ops_refunds")}, headers=BUILDER)
    assert saved.status_code == 201, saved.text
    base = (await c.get(wf, headers=BUILDER)).json()["data"]["saveBase"]
    body = {"definition": definition("ops_refunds") | {"name": "Unpublished"}}
    body |= {"baseVersion": base["version"], "baseDigest": base["digest"]}
    assert (await c.put(f"{wf}/working-copy", json=body, headers=BUILDER)).status_code == 200
    reads = {
        "/v1/workflows/definitions": {},
        "/v1/workflows/definitions/account-uses": {"app": "gmail", "name": "ops"},
        wf: {},
        f"{wf}/versions/{base['version']}/shapes": {},
        f"{wf}/sample": {"step": "small"},
        f"{wf}/diff": {"from": "1", "to": "working-copy"},
        f"{wf}/publish-preview": {},
    }
    gets = {r.path for r in engine_router.routes if isinstance(r, APIRoute) and "GET" in (r.methods or set())}
    templates = {
        p.replace("ops_refunds", "{workflow_id}").replace(f"/{base['version']}/", "/{version}/") for p in reads
    }
    assert {g for g in gets if g.startswith("/v1/workflows/definitions")} == templates
    for path, params in reads.items():
        for who in (NOT_A_WORKFLOW_READER, CHAT_USER):
            refused = await c.get(path, params=params, headers=who)
            assert refused.status_code == 403, f"{path}: {refused.status_code} {refused.text}"
        # Publish preview also needs the publish cell, which a viewer does not hold.
        reader = BUILDER if path.endswith("publish-preview") else VIEWER
        read = await c.get(path, params=params, headers=reader)
        assert read.status_code == 200, f"{path}: {read.status_code} {read.text}"
    assert (await c.get(wf, headers=VIEWER)).json()["data"]["workingCopy"]["definition"]["name"] == "Unpublished"
    # A step form's picker lists the area's records only to a caller its own list would answer.
    picker = "/v1/workflows/option-sources"
    for source in ("workflows", "agents", "tools"):
        refused = await c.get(picker, params={"source": source}, headers=CHAT_USER)
        assert refused.status_code == 403, f"{source}: {refused.status_code} {refused.text}"
    assert (await c.get(picker, params={"source": "workflows"}, headers=NOT_A_WORKFLOW_READER)).status_code == 403
    assert (await c.get(picker, params={"source": "agents"}, headers=NOT_A_WORKFLOW_READER)).status_code == 200
    assert (await c.get(picker, params={"source": "workflows"}, headers=VIEWER)).status_code == 200
