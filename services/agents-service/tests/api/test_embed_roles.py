"""Who may create an embed and mint its keys (orch, embed UX run 2026-10-19), with tokens as platform-service mints
them, by failure mode: a viewer creates an embed, mints a key, or changes one; a builder of the agent's team does.
On the shared dev stack every seeded person also holds Admin in every team (OPS_SEED_EVERYONE_ADMIN), so a "Viewer"
there acts as an admin; these tokens carry only the roles the grid gives."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient
from pydantic_ai.models.test import TestModel

from tests.engine.test_lifecycle_rights import BUILDER, VIEWER

from .role_app import ok, role_app

AGENT = "ag_branch"
EMBED = {"name": "Intranet help", "agentId": AGENT, "origins": ["https://intranet.bank.example"]}


@pytest.fixture
async def c() -> AsyncIterator[AsyncClient]:
    async with role_app(TestModel()) as client:
        yield client


async def test_a_viewer_creates_no_embed_and_mints_no_key(c: AsyncClient) -> None:
    refused = await c.post("/v1/widget-deployments", json=EMBED, headers=VIEWER)
    assert refused.status_code == 403, refused.text
    made = ok(await c.post("/v1/widget-deployments", json=EMBED, headers=BUILDER), 201)
    mint = await c.post(f"/v1/widget-deployments/{made['id']}/keys", json={"name": "Server"}, headers=VIEWER)
    assert mint.status_code == 403, mint.text
    paused = await c.patch(f"/v1/channels/{made['id']}", json={"paused": True}, headers=VIEWER)
    assert paused.status_code == 403, paused.text


async def test_a_builder_creates_an_embed_and_mints_its_key(c: AsyncClient) -> None:
    made = ok(await c.post("/v1/widget-deployments", json=EMBED, headers=BUILDER), 201)
    key = ok(await c.post(f"/v1/widget-deployments/{made['id']}/keys", json={"name": "Server"}, headers=BUILDER), 201)
    assert key.get("secret"), key
