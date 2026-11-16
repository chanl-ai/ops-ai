"""What the registry's tenant isolation must keep working, on PostgreSQL through the tenant role, by failure mode: a
restart that serves only one tenant's published agents; an agent read by id or found by its slug in the caller's own
tenant failing; a public widget mint key or session that no longer finds its deployment and agent; a thread started
through a channel deployment refused; the workflow refs a service reads coming back empty; the dev seed not loading.
Each test starts agents-service on the shared test database with two tenants of its own."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.api.app import create_app
from ops_agents.api.deps import Runtime
from ops_agents.store.agent_registry import AgentRegistry, registry_agents
from ops_agents.store.channels import ChannelStore, Deployment
from ops_agents.store.tenancy import LOCAL_TENANT, tenant_scope
from ops_agents.store.workflow_registry import registry_workflows
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import Ed25519Signer, mint
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model

PLATFORM = Ed25519Signer.generate("registry-pins")
ORIGIN = "https://intranet.bank.example"
# A team of this module's own, so a list reads none of the other tests' agents on the shared database.
TEAM = f"team_{new_id('pin')}"


def person(tenant: str, team: str = TEAM, role: str = "builder") -> dict[str, str]:
    claims = {
        "sub": f"usr_{tenant}",
        "email": f"builder@{tenant}.example",
        "name": "Pat",
        "kind": "person",
        "security_team": "team_security",
        "aud": ["agents"],
        "tenant_id": tenant,
        "team_ids": [team],
        "roles": {team: role},
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": team}


async def _jwks() -> dict[str, Any]:
    return {"keys": [PLATFORM.public_jwk()]}


async def _introspect(_key: str) -> dict[str, Any] | None:
    return None


@asynccontextmanager
async def started(url: str, *, seed: bool = True) -> AsyncGenerator[tuple[AsyncClient, Runtime]]:
    """One start of agents-service on the test database, as a restart of a deployment is."""
    settings = Settings(database_url=url, seed_dir=SEED if seed else None, embed_origins=["http://test"])
    engine = create_async_engine(url)
    app = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        auth=Auth(
            Identity(audience="agents", jwks=_jwks, introspect=_introspect, key_cache_s=0),
            ServiceAuth(audience="agents", verifiers=service_verifiers(settings, "agents")),
        ),
        knowledge=fixture_knowledge(),
    )
    try:
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            yield client, app.state.runtime
    finally:
        await engine.dispose()


async def published_agent(client: AsyncClient, rt: Runtime, tenant: str, name: str) -> str:
    made = await client.post("/v1/agents", json={"name": name, "role": "Answers"}, headers=person(tenant))
    assert made.status_code == 201, made.text
    agent_id = str(made.json()["data"]["id"])
    with tenant_scope(tenant):
        await AgentRegistry(rt.db).publish(agent_id, 1, by=f"approver@{tenant}.example", review_id="rv_pin")
    return agent_id


def tenants() -> tuple[str, str]:
    return f"t_{new_id('a')}", f"t_{new_id('b')}"


async def test_a_restart_serves_each_tenants_published_agents_and_each_reads_its_own(database_url: str) -> None:
    a, b = tenants()
    async with started(database_url) as (client, rt):
        agent_a = await published_agent(client, rt, a, "Payee desk")
        agent_b = await published_agent(client, rt, b, "Refund desk")
    async with started(database_url) as (client, rt):
        assert rt.catalog.agent(agent_a) is not None
        assert rt.catalog.agent(agent_b) is not None
        for tenant, agent, slug in ((a, agent_a, "payee-desk"), (b, agent_b, "refund-desk")):
            read = await client.get(f"/v1/agents/{agent}", headers=person(tenant))
            assert read.status_code == 200, read.text
            assert read.json()["data"]["slug"].startswith(slug)
            found = await client.get("/v1/agents", params={"search": slug}, headers=person(tenant))
            assert agent in [r["id"] for r in found.json()["data"]["data"]], found.text
            chat = await client.post("/v1/chat/threads", json={"agentId": agent, "kbIds": []}, headers=person(tenant))
            assert chat.status_code == 201, chat.text


async def test_a_widget_mint_key_and_its_session_find_their_deployment_and_agent(database_url: str) -> None:
    _, b = tenants()
    async with started(database_url) as (client, rt):
        agent = await published_agent(client, rt, b, "Widget desk")
    async with started(database_url) as (client, rt):
        made = await client.post(
            "/v1/widget-deployments",
            json={"name": "Intranet help", "agentId": agent, "origins": [ORIGIN]},
            headers=person(b),
        )
        assert made.status_code == 201, made.text
        dep = str(made.json()["data"]["id"])
        key = await client.post(f"/v1/widget-deployments/{dep}/keys", json={"name": "server"}, headers=person(b))
        assert key.status_code == 201, key.text
        minted = await client.post(
            f"/v1/widget-deployments/{dep}/sessions",
            json={"email": "banker@bank.example", "name": "Banker", "origin": ORIGIN},
            headers={"Authorization": f"Bearer {key.json()['data']['secret']}"},
        )
        assert minted.status_code == 201, minted.text
        page = {"X-Widget-Session": minted.json()["data"]["session"], "Origin": ORIGIN}
        thread = await client.post(f"/v1/widget/{dep}/threads", headers=page)
        assert thread.status_code == 201, thread.text


async def test_a_thread_starts_through_its_tenants_channel_deployment(database_url: str) -> None:
    a, _ = tenants()
    async with started(database_url, seed=False) as (client, rt):
        dep = new_id("dep")
        with tenant_scope(a):
            await ChannelStore(rt.db).put_deployment(
                Deployment(dep, "simple_workflow", "email", False, "enqueue", team_id=TEAM), now_iso()
            )
        body: dict[str, Any] = {
            "graph": "simple_workflow",
            "metadata": {},
            "externalKey": f"mail:{dep}",
            "deploymentId": dep,
        }
        made = await client.post("/v1/threads", json=body, headers=person(a))
        assert made.status_code == 201, made.text
        again = await client.post("/v1/threads", json=body, headers=person(a))
        assert again.status_code == 200 and again.json()["data"]["threadId"] == made.json()["data"]["threadId"]


async def test_workflow_refs_list_the_tenants_workflows(database_url: str) -> None:
    a, _ = tenants()
    async with started(database_url) as (client, _rt):
        made = await client.post("/v1/workflows", json={"name": "Refs pin flow"}, headers=person(a))
        assert made.status_code == 201, made.text
        wid = str(made.json()["data"]["id"])
        mine = await client.get("/v1/workflow-refs", headers=person(a))
        assert mine.status_code == 200, mine.text
        assert wid in [r["id"] for r in mine.json()["data"]]


async def test_the_dev_seed_loads_into_the_local_tenant(database_url: str) -> None:
    async with started(database_url) as (_client, rt):
        assert rt.catalog.agent("ag_fraud") is not None
        engine = rt.db
        async with engine.connect() as c:
            agents = (
                await c.execute(sa.select(registry_agents.c.tenant_id).where(registry_agents.c.id == "ag_fraud"))
            ).scalars()
            assert list(agents) == [LOCAL_TENANT]
            flows = (await c.execute(sa.select(sa.func.count()).select_from(registry_workflows))).scalar_one()
            assert flows > 0
