"""models-service in-process on the compose PostgreSQL (`make db-up`), migrated by its own chain and seeded, and on a
scratch SQL Server database holding the chain's golden DDL when OPS_MSSQL_SERVER and MSSQL_SA_PASSWORD are set
(ops_store.testing): every test that asks for `database_url` runs on both."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator, AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_identity import dev_service_signer, mint_service_token
from ops_models.app import create_models_app
from ops_models.seed import seed
from ops_service_kit.contract import response_checker
from ops_service_kit.settings import Settings
from ops_service_kit.testapps import released_apps
from ops_service_kit.testdb import isolate_from_stack, refusal, use_worker_database
from ops_store.database import open_database
from ops_store.testing import DATABASES, NO_SQL_SERVER, postgresql_only, sql_server_schema

ROOT = Path(__file__).parents[1]
# agents-service's Ed25519 token for models-service's internal routes (dev key, dev only), naming its tenant.
SERVICE = {
    "Authorization": "Bearer "
    + mint_service_token(dev_service_signer(), service="agents", audience="models", tenant_id="local", ttl_s=3600)
}


# A caller's own tenant, as every real caller names it: the call log is that tenant's, read by its service token.
LOCAL = {"X-Tenant-Id": "local"}


def _service(tenant: str) -> dict[str, str]:
    token = mint_service_token(dev_service_signer(), service="agents", audience="models", tenant_id=tenant, ttl_s=3600)
    return {"Authorization": f"Bearer {token}"}


def pytest_configure(config: pytest.Config) -> None:
    use_worker_database()
    isolate_from_stack()
    # Before any fixture or migration: the test database only, never the live one (ops_service_kit.testdb).
    if (why := refusal(Settings().database_url, os.environ.get("OPS_TEST_DATABASE_URL"))) is not None:
        pytest.exit(why, returncode=4)
    config.addinivalue_line("markers", "postgresql_only(why): runs on PostgreSQL only, for the reason given")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    keep, dropped = postgresql_only(items)
    if dropped:
        config.hook.pytest_deselected(items=[i for i in items if i not in keep])
        items[:] = keep
        terminal = config.pluginmanager.get_plugin("terminalreporter")
        for nodeid, why in dropped:
            if terminal is not None:
                terminal.write_line(f"postgresql only: {nodeid}: {why}")


@pytest.fixture(scope="session", params=DATABASES)
def database_url(request: pytest.FixtureRequest) -> Iterator[str]:
    if request.param == "postgresql":
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        yield Settings().database_url
        return
    with sql_server_schema("models", os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")) as url:
        if url is None:
            pytest.skip(NO_SQL_SERVER)
        yield url


# SQL Server has no row_security setting: the administrator turns the call log's tenant policy off, in the transaction,
# when the policy exists (models_0012 adds it). Deferred in EXEC, as SQL Server resolves the name when it compiles.
CALL_LOG_POLICY = "ops_security.model_call_log_tenant"
_MSSQL_POLICY = (
    f"IF OBJECT_ID(N'{CALL_LOG_POLICY}', N'SP') IS NOT NULL "
    f"EXEC (N'ALTER SECURITY POLICY {CALL_LOG_POLICY} WITH (STATE = {{}})')"
)


@asynccontextmanager
async def past_the_call_log_policy(c: AsyncConnection) -> AsyncGenerator[None]:
    """The database owner's statements in this block read and write the call log past its tenant policy."""
    if c.dialect.name != "mssql":
        await c.execute(sa.text("SET LOCAL row_security = off"))
        yield
        return
    await c.execute(sa.text(_MSSQL_POLICY.format("OFF")))
    yield
    await c.execute(sa.text(_MSSQL_POLICY.format("ON")))


@dataclass
class Models:
    client: httpx.AsyncClient
    engine: AsyncEngine
    app: Any = None

    async def key(self, budget: str = "1", **extra: Any) -> tuple[str, str]:
        """A fresh key for a unique identity; returns (id, secret)."""
        # After "_", a run of digits is never masked as an account number in the log lines tests read.
        key_id = f"workflow:test_{uuid4().hex[:8]}"
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

    async def calls(self, key_id: str, tenant: str = "local") -> list[dict[str, Any]]:
        """The key's calls that `tenant` made, every page of them, read with a service token naming it."""
        found: list[dict[str, Any]] = []
        page = 1
        while True:
            params = {"keyId": key_id, "page": page}
            r = await self.client.get("/v1/models/calls", params=params, headers=_service(tenant))
            body = r.json()["data"]
            found += body["data"]
            if not body["pagination"]["hasNext"]:
                return found
            page += 1

    async def spent(self, key_id: str) -> Decimal:
        listed = await self.client.get("/v1/models/keys", params={"ids": key_id}, headers=SERVICE)
        keys = listed.json()["data"]["data"]
        return Decimal(next(k for k in keys if k["id"] == key_id)["spent"])


@pytest.fixture
async def models(database_url: str) -> AsyncIterator[Models]:
    # open_database, as __main__ opens it: its listeners count each request's statements and transactions.
    engine = open_database(database_url)
    await seed(engine)
    app = create_models_app(engine, overlap_seconds=2)
    # Every JSON response is checked against the app's own OpenAPI document.
    hooks = {"response": [response_checker(app)]}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://models", event_hooks=hooks) as client:
        yield Models(client, engine, app)
    await engine.dispose()


@pytest.fixture(autouse=True)
def _release_apps() -> Iterator[None]:
    yield from released_apps()
