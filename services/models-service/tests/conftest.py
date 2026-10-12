"""models-service in-process on the compose PostgreSQL (`make db-up`), migrated by its own chain and seeded."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_identity import dev_service_signer, mint_service_token
from ops_models.app import create_models_app
from ops_models.seed import seed
from ops_service_kit.contract import response_checker
from ops_service_kit.settings import Settings
from ops_service_kit.testdb import refusal

ROOT = Path(__file__).parents[1]
# agents-service's Ed25519 token for models-service's internal routes (dev key, dev only), naming its tenant.
SERVICE = {
    "Authorization": "Bearer "
    + mint_service_token(dev_service_signer(), service="agents", audience="models", tenant_id="local", ttl_s=3600)
}


def pytest_configure(config: pytest.Config) -> None:
    # Before any fixture or migration: the test database only, never the live one (ops_service_kit.testdb).
    if (why := refusal(Settings().database_url, os.environ.get("OPS_TEST_DATABASE_URL"))) is not None:
        pytest.exit(why, returncode=4)


@pytest.fixture(scope="session")
def database_url() -> str:
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    return Settings().database_url


@dataclass
class Models:
    client: httpx.AsyncClient
    engine: AsyncEngine
    app: Any = None

    async def key(self, budget: str = "1", **extra: Any) -> tuple[str, str]:
        """A fresh key for a unique identity; returns (id, secret)."""
        key_id = f"workflow:test-{uuid4().hex[:8]}"
        body = {"id": key_id, "kind": "workflow", "budget": budget, **extra}
        r = await self.client.post("/v1/models/keys", json=body, headers=SERVICE)
        assert r.status_code == 201, r.text
        return key_id, str(r.json()["data"]["secret"])

    async def complete(self, secret: str, alias: str = "bank-standard", **headers: str) -> httpx.Response:
        body = {
            "model": alias,
            "messages": [{"role": "user", "content": "Summarise the dispute for case DSP-2210 please"}],
        }
        return await self.client.post(
            "/v1/models/chat/completions", json=body, headers={"Authorization": f"Bearer {secret}", **headers}
        )

    async def calls(self, key_id: str) -> list[dict[str, Any]]:
        r = await self.client.get("/v1/models/calls", params={"keyId": key_id}, headers=SERVICE)
        return r.json()["data"]["items"]

    async def spent(self, key_id: str) -> Decimal:
        keys = (await self.client.get("/v1/models/keys", headers=SERVICE)).json()["data"]
        return Decimal(next(k for k in keys if k["id"] == key_id)["spent"])


@pytest.fixture
async def models(database_url: str) -> AsyncIterator[Models]:
    engine = create_async_engine(database_url)
    await seed(engine)
    app = create_models_app(engine, overlap_seconds=2)
    # Every JSON response is checked against the app's own OpenAPI document.
    hooks = {"response": [response_checker(app)]}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://models", event_hooks=hooks) as client:
        yield Models(client, engine, app)
    await engine.dispose()
