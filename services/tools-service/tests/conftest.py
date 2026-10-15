"""tools-service against the compose PostgreSQL (`make db-up`), on the test database `make test` migrates. Each test
works in its own tenant, so tests never see each other's modules."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.activities.catalog import load_catalog
from ops_identity import Auth, Identity, dev_service_signer, mint_service_token
from ops_service_kit import opa_server
from ops_service_kit.contract import response_checker
from ops_service_kit.settings import Settings
from ops_service_kit.testdb import refusal
from ops_tools.app import create_gateway_app
from ops_tools.egress import EgressPolicy
from ops_tools.egress_routes import egress_router
from ops_tools.modules.directory import Directory
from ops_tools.modules.routes import executions_router, modules_router
from ops_tools.modules.seed import load
from ops_tools.modules.service import ModuleService
from ops_tools.modules.workflows import StaticWorkflows, WorkflowDirectory
from ops_tools.opa import OpaClient
from ops_tools.registry import ToolRegistry
from ops_tools.secrets import SecretResolver
from ops_tools.secrets.cipher import AesGcmCipher
from ops_tools.secrets.routes import secrets_router
from ops_tools.store import CallLog
from ops_tools.store.egress import EgressStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.secrets import SecretStore
from ops_tools.tools import LocalToolRunner

from .fake_mcp import tools as fake_tools
from .fake_upstream import fake_bank

FIXTURES = Path(__file__).parent / "fixtures"
# This process's own OPA, never the shared one on :8181, whose key and policy any tools-service start rewrites.
OPA_URL = opa_server.session_url()
REVIEW_KEY = "test-review-key"


def pytest_configure(config: pytest.Config) -> None:
    # Before any fixture or migration: the test database only, never the live one (ops_service_kit.testdb).
    if (why := refusal(Settings().database_url, os.environ.get("OPS_TEST_DATABASE_URL"))) is not None:
        pytest.exit(why, returncode=4)


@pytest.fixture(autouse=True)
def _no_dev_egress_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dev .env maps a fake bank's name with OPS_EGRESS_RESOLVE, which Settings refuses outside dev; tests build their
    own resolution and never read the stack's."""
    monkeypatch.delenv("OPS_EGRESS_RESOLVE", raising=False)


@pytest.fixture(scope="session")
def seed() -> dict[str, Any]:
    return json.loads((FIXTURES / "tool_modules.json").read_text())


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(Settings().database_url)
    yield e
    await e.dispose()


@pytest.fixture
def store(engine: AsyncEngine) -> ModuleStore:
    return ModuleStore(engine)


@pytest.fixture
def tenant() -> str:
    return f"t_{uuid4().hex[:10]}"


@dataclass
class Api:
    client: httpx.AsyncClient
    tenant: str

    async def call(
        self, method: str, path: str, *, user: str | None = None, team: str | None = None, **kw: Any
    ) -> httpx.Response:
        headers = {**({"X-Dev-User": user} if user else {}), **({"X-Team-Id": team} if team else {})}
        return await self.client.request(method, f"/v1/tool-modules{path}", headers=headers, **kw)


@pytest.fixture(scope="session")
def catalog_tools() -> list[dict[str, Any]]:
    return json.loads((Settings().seed_dir / "tools.json").read_text())


def test_auth(settings: Settings, tenant: str, user: str, *, dev: bool) -> Auth:
    """The shared auth on this test's tenant: dev's fixed user, or production, where dev headers are refused and only
    a service token is accepted."""
    if dev:
        return Auth.for_dev(settings, audience="tools", name=user, email=user, tenant_id=tenant)
    dev_only = Auth.for_dev(settings, audience="tools", name=user, email=user, tenant_id=tenant)
    return Auth(Identity(audience="tools", jwks=no_keys, introspect=no_api_keys), dev_only.services)


async def no_keys() -> dict[str, Any]:
    return {"keys": []}


async def no_api_keys(_key: str) -> dict[str, Any] | None:
    return None


def service_headers(tenant: str, service: str = "agents") -> dict[str, str]:
    """A calling service's Ed25519 token for tools-service (dev key), naming the tenant it calls for."""
    token = mint_service_token(dev_service_signer(), service=service, audience="tools", tenant_id=tenant)
    return {"Authorization": f"Bearer {token}"}


def build_app(
    engine: AsyncEngine,
    seed: dict[str, Any],
    tenant: str,
    *,
    opa: httpx.AsyncClient | None = None,
    upstream: httpx.AsyncClient | None = None,
    dev: bool = True,
    auth: Auth | None = None,
    workflows: WorkflowDirectory | None = None,
) -> FastAPI:
    """The gateway app as __main__ builds it, on the tenant's registry. `opa` defaults to an address nothing answers,
    for tests that never reach a decision; `upstream` is what http operations call."""
    settings = Settings()
    catalog = load_catalog(settings.seed_dir)
    directory = Directory.from_seed(seed, datetime.now(UTC))
    store, calls = ModuleStore(engine), CallLog(engine)
    policy = EgressPolicy(EgressStore(engine))
    cipher = AesGcmCipher(settings.secrets_key.get_secret_value())
    resolver = SecretResolver(SecretStore(engine), cipher)
    service = ModuleService(
        store,
        directory,
        calls,
        egress=policy,
        http=upstream,
        secrets=resolver,
        workflows=workflows or StaticWorkflows(seed.get("workflows", [])),
    )
    return create_gateway_app(
        opa=OpaClient(opa or httpx.AsyncClient(base_url="http://opa.invalid")),
        registry=ToolRegistry(catalog, store, tenant_id=tenant),
        log=calls,
        runner=LocalToolRunner(catalog),
        review_key=REVIEW_KEY,
        auth=auth or test_auth(settings, tenant, seed["currentUser"], dev=dev),
        routers=(
            modules_router(service, directory),
            executions_router(service, directory),
            egress_router(EgressStore(engine)),
            secrets_router(SecretStore(engine), cipher),
        ),
        http_client=upstream,
        egress=policy,
        secret_resolver=resolver,
    )


@pytest.fixture(params=[True], ids=["dev"])
def dev(request: pytest.FixtureRequest) -> bool:
    """Whether the app runs as in dev, where X-Dev-User is honoured; a test parametrizes it to run as production."""
    return bool(request.param)


@pytest.fixture
async def api(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]], dev: bool
) -> AsyncIterator[Api]:
    """A seeded tenant behind the real routes; every JSON response is checked against openapi.json's schemas."""
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    app = build_app(engine, seed, tenant, dev=dev)
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        yield Api(c, tenant)


@dataclass
class Bank:
    api: Api
    received: list[dict[str, Any]]
    mcp_tools: list[dict[str, Any]]


@pytest.fixture
async def bank(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Bank]:
    """A seeded tenant whose outbound requests go to the in-process fake bank, with OPA from the compose stack."""
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    mcp_tools = fake_tools()
    fake, received = fake_bank(mcp_tools)
    async with (
        httpx.AsyncClient(base_url=OPA_URL) as opa,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=fake)) as upstream,
    ):
        app = build_app(engine, seed, tenant, opa=opa, upstream=upstream)
        hooks = {"response": [response_checker(app)]}
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
            ) as client,
        ):
            yield Bank(Api(client, tenant), received, mcp_tools)


@pytest.fixture
def bank_api(bank: Bank) -> Api:
    return bank.api


@pytest.fixture
def received(bank: Bank) -> list[dict[str, Any]]:
    return bank.received


@pytest.fixture
def gateway_call(bank: Bank, engine: AsyncEngine) -> Any:
    """Publishes the tenant's document-service draft, then calls one of its tools through /v1/calls."""

    async def call(tool: str, args: dict[str, Any]) -> httpx.Response:
        store = ModuleStore(engine)
        m = await store.get(bank.api.tenant, "mod_document_service")
        assert m is not None
        if m["status"] != "published":
            await store.put({**m, "status": "published"}, expected_revision=m["revision"])
        body = {"tool": tool, "input": args, "key": "s1", "runContext": {"act": "workflow:dispute_email"}}
        return await bank.api.client.post("/v1/calls", json=body, headers=service_headers(bank.api.tenant))

    return call
