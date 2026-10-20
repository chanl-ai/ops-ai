"""Agents carry a template id and a protection level (c-180), by failure mode: a provisioned agent not found again by
its template id, a person setting either field, a person changing a system agent, a managed agent losing its template id
on an edit, and an agent from before reading as protected."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_engine.store import metadata as engine_metadata
from ops_identity import Auth, Identity, ServiceAuth, dev_service_signer, mint_service_token, service_verifiers
from ops_service_kit.settings import Settings
from tests.engine.test_lifecycle_rights import ADMIN, BUILDER, jwks

# Signed-in people: a builder of team_ops, and its admin, who also holds agents.manage (c-180).
PERSON = BUILDER
SCOPES = ["agents:provision", "agents:create", "agents:edit", "agents:delete", "agents:view"]


def provisioner(scopes: list[str] = SCOPES) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(),
        service="platform",
        audience="agents",
        tenant_id="acme",
        scopes=scopes,
        team_id="team_ops",
    )
    return {"Authorization": f"Bearer {token}"}


async def _no_keys(_key: str) -> dict[str, Any] | None:
    return None


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=None, service_scopes={"platform": SCOPES})
    # The app builds a Postgres checkpointer from the database URL unless it is handed one.
    services = ServiceAuth(
        audience="agents", verifiers=service_verifiers(settings, "agents"), scopes=settings.service_scopes
    )
    auth = Auth(Identity(audience="agents", jwks=jwks, introspect=_no_keys, key_cache_s=0, services=services), services)
    app = create_app(settings, engine=engine, checkpointer=InMemorySaver(), auth=auth)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield c


def _data(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"]


async def _provisioned(c: AsyncClient, protection: str) -> dict[str, Any]:
    body = {"name": "Branch assistant", "role": "Helps branch staff", "templateId": "banking/branch-assistant"}
    return _data(await c.post("/v1/agents", json={**body, "protection": protection}, headers=provisioner()), 201)


async def test_a_provisioned_agent_is_found_again_by_its_template_id(client: AsyncClient) -> None:
    made = await _provisioned(client, "managed")
    _data(await client.post("/v1/agents", json={"name": "Other", "role": "Other"}, headers=PERSON), 201)
    found = _data(await client.get("/v1/agents", params={"templateId": "banking/branch-assistant"}, headers=PERSON))
    assert [a["id"] for a in found["data"]] == [made["id"]]
    assert (made["templateId"], made["protection"]) == ("banking/branch-assistant", "managed")


async def test_only_the_provisioner_sets_template_fields(client: AsyncClient) -> None:
    body = {"name": "Mine", "role": "Mine", "templateId": "banking/branch-assistant"}
    refused = await client.post("/v1/agents", json=body, headers=PERSON)
    assert (refused.status_code, refused.json()["error"]["code"]) == (403, "provisioner_only"), refused.text
    unscoped = await client.post("/v1/agents", json=body, headers=provisioner(["agents:create"]))
    assert unscoped.status_code == 403, unscoped.text
    own = _data(await client.post("/v1/agents", json={"name": "Mine", "role": "Mine"}, headers=PERSON), 201)
    locked = await client.patch(f"/v1/agents/{own['id']}", json={"protection": "system"}, headers=PERSON)
    assert (locked.status_code, locked.json()["error"]["code"]) == (403, "provisioner_only"), locked.text


async def test_a_system_agent_is_changed_by_an_admin_or_the_provisioner_not_a_builder(client: AsyncClient) -> None:
    made = await _provisioned(client, "system")
    edit = await client.patch(f"/v1/agents/{made['id']}", json={"role": "Changed"}, headers=PERSON)
    assert (edit.status_code, edit.json()["error"]["code"]) == (403, "system_record"), edit.text
    gone = await client.delete(f"/v1/agents/{made['id']}", headers=PERSON)
    assert (gone.status_code, gone.json()["error"]["code"]) == (403, "system_record"), gone.text
    _data(await client.patch(f"/v1/agents/{made['id']}", json={"role": "Synced"}, headers=provisioner()))
    _data(await client.patch(f"/v1/agents/{made['id']}", json={"role": "Admin's"}, headers=ADMIN))


async def test_a_managed_agent_is_edited_and_keeps_its_template(client: AsyncClient) -> None:
    made = await _provisioned(client, "managed")
    after = _data(await client.patch(f"/v1/agents/{made['id']}", json={"role": "Team's own"}, headers=PERSON))
    assert (after["role"], after["templateId"], after["protection"]) == (
        "Team's own",
        "banking/branch-assistant",
        "managed",
    )


async def test_an_agent_made_without_a_template_reads_as_neither(client: AsyncClient) -> None:
    own = _data(await client.post("/v1/agents", json={"name": "Plain", "role": "Plain"}, headers=PERSON), 201)
    assert (own["templateId"], own["protection"]) == (None, None)
    _data(await client.patch(f"/v1/agents/{own['id']}", json={"role": "Edited"}, headers=PERSON))
