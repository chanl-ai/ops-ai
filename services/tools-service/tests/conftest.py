"""tools-service against the compose PostgreSQL (`make db-up`), on the test database `make test` migrates. Each test
works in its own tenant, so tests never see each other's modules."""

from __future__ import annotations

import faulthandler
import json
import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.activities.catalog import Catalog, load_catalog
from ops_email import MemorySender
from ops_identity import Auth, Identity, dev_service_signer, mint_service_token
from ops_policy import AesGcmCipher
from ops_service_kit import opa_server
from ops_service_kit.contract import response_checker
from ops_service_kit.logging import quiet_request_logs
from ops_service_kit.settings import Settings
from ops_service_kit.testdb import isolate_from_stack, refusal
from ops_tools.app import create_gateway_app
from ops_tools.auth import Authenticator, Tokens
from ops_tools.auth.discovery import Discovery
from ops_tools.connections.routes import connections_router
from ops_tools.connections.service import ConnectionService
from ops_tools.egress import EgressPolicy
from ops_tools.egress_routes import egress_router
from ops_tools.mock_routes import mocks_router
from ops_tools.modules.directory import Directory
from ops_tools.modules.routes import executions_router, modules_router
from ops_tools.modules.seed import load
from ops_tools.modules.service import ModuleService
from ops_tools.modules.workflows import StaticWorkflows, WorkflowDirectory
from ops_tools.opa import OpaClient
from ops_tools.registry import ToolRegistry
from ops_tools.secrets import SecretResolver
from ops_tools.secrets.routes import secrets_router
from ops_tools.send_policy_routes import send_policy_router
from ops_tools.store import CallLog
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.egress import EgressStore
from ops_tools.store.mocks import MockStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.secrets import SecretStore
from ops_tools.store.send_policies import SendPolicies
from ops_tools.tools import LocalToolRunner

from .fake_mcp import tools as fake_tools
from .fake_upstream import fake_bank

# agents-service's fixture catalogue, which these tests run the gateway on; the services read their own seed/.
AGENTS_FIXTURES = Path(__file__).resolve().parents[2] / "agents-service" / "tests" / "fixtures" / "seed"

FIXTURES = Path(__file__).parent / "fixtures"
# This process's own OPA, never the shared one on :8181, whose key and policy any tools-service start rewrites.
OPA_URL = opa_server.session_url()


def opa_client() -> httpx.AsyncClient:
    """The tests' client for the stack's OPA. Generous on reads: the app's start-up PUTs the review key there, and on a
    loaded machine (image builds running) OPA took past httpx's 5 s default, failing tests in setup."""
    return httpx.AsyncClient(base_url=OPA_URL, timeout=httpx.Timeout(5.0, read=30.0))


REVIEW_KEY = "test-review-key"
# Where a connection's sign-in returns (c-330): the console's page, which the tests stand in for.
CONSOLE_URL = "https://console.bank.test"

# Tests call the fake upstreams with their own httpx clients, outside the gateway app; their request lines would
# carry resolved secrets into the captured logs that test_workbench_runs scans.
quiet_request_logs()


def pytest_configure(config: pytest.Config) -> None:
    _hang_out.append(os.fdopen(os.dup(2), "w"))
    isolate_from_stack()
    # Before any fixture or migration: the test database only, never the live one (ops_service_kit.testdb).
    if (why := refusal(Settings().database_url, os.environ.get("OPS_TEST_DATABASE_URL"))) is not None:
        pytest.exit(why, returncode=4)


# A test that waits forever on a child process or a socket held QA's whole run for over an hour on 409d50d9 (a
# forkserver and its resource tracker alive, verify-head's timeout never reached). Past this many seconds the run prints
# every thread's stack, which names the test, and exits non-zero.
HANG_SECONDS = float(os.environ.get("OPS_TEST_HANG_SECONDS", "300"))
# The run's own stderr, copied in pytest_configure while capture is off: a dump into a test's capture would vanish
# with the exit.
_hang_out: list[Any] = []


@pytest.fixture(autouse=True)
def _fail_fast_when_hung() -> Iterator[None]:
    faulthandler.dump_traceback_later(HANG_SECONDS, exit=True, file=_hang_out[0])
    yield
    faulthandler.cancel_dump_traceback_later()


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


class FakeReviews:
    """agents-service's Reviews for tests that do not run it (c-163): records each review opened and gives it an id.
    agents-service's own tests cover who may open and decide."""

    def __init__(self) -> None:
        self.opened: list[dict[str, Any]] = []

    async def open(self, credentials: dict[str, str], **kw: Any) -> str:
        self.opened.append({"credentials": credentials, **kw})
        return f"TMP-{1000 + len(self.opened)}"


@dataclass
class Api:
    client: httpx.AsyncClient
    tenant: str

    async def call(
        self, method: str, path: str, *, user: str | None = None, team: str | None = None, **kw: Any
    ) -> httpx.Response:
        headers = {
            **({"X-Dev-User": user} if user else {}),
            **({"X-Team-Id": team} if team else {}),
            **kw.pop("headers", {}),
        }
        return await self.client.request(method, f"/v1/tool-modules{path}", headers=headers, **kw)

    async def decide(self, module: str, decision: str = "approved", reason: str | None = None) -> httpx.Response:
        """Decides the module's open review as Reviews would, with agents-service's token."""
        detail = (await self.call("GET", f"/{module.lstrip('/')}")).json()["data"]
        v = next(x for x in detail["versions"] if x["status"] == "in_review")
        body = {
            "requestId": v["reviewId"],
            "version": v["version"],
            "decision": decision,
            "reason": reason,
            "by": "Nadia Petrov",
        }
        return await self.call(
            "POST", f"/{module.lstrip('/')}/review-decisions", json=body, headers=service_headers(self.tenant)
        )


@pytest.fixture(scope="session")
def local_catalog() -> Catalog:
    """agents-service's fixture catalogue, which the local runner runs; tests take it here, never from ops_agents."""
    return load_catalog(AGENTS_FIXTURES)


@pytest.fixture(scope="session")
def catalog_tools() -> list[dict[str, Any]]:
    """agents-service's fixture tools, minus its stand-ins for the fake bank's operations (c-057): a tenant here
    imports the bank's document itself, and an operation name held by another module refuses the import."""
    tools: list[dict[str, Any]] = json.loads((AGENTS_FIXTURES / "tools.json").read_text())
    return [t for t in tools if t.get("server") != "Harbor & Pine Core Banking"]


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


def service_headers(tenant: str, service: str = "agents", scopes: list[str] | None = None) -> dict[str, str]:
    """A calling service's Ed25519 token for tools-service (dev key), naming the tenant it calls for; agents-service
    claims `tools:view` for the grantable operations (c-168) unless `scopes` says otherwise."""
    claimed = scopes if scopes is not None else (["tools:view"] if service == "agents" else [])
    token = mint_service_token(
        dev_service_signer(), service=service, audience="tools", tenant_id=tenant, scopes=claimed
    )
    return {"Authorization": f"Bearer {token}"}


async def grant(engine: AsyncEngine, tenant: str, module_id: str, approval_id: str) -> None:
    """Test setup: a workflow's access request approved, as its system workflow's apply step would leave it (c-257;
    that path is tested in test_apply_tool_access and agents-service's gateway tests)."""
    store = ModuleStore(engine)
    m = await store.get(tenant, module_id)
    assert m is not None
    a = next(x for x in m["approvals"] if x["id"] == approval_id)
    a.update(status="approved", decided_by="Maya Okafor", decided_at=datetime.now(UTC))
    await store.put(m, expected_revision=m["revision"])


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
    reviews: Any = None,
    publish_policy: Any = None,
    cases: Any = None,
    write_approvals: Any = None,
    send_check: Any = None,
    mcp: bool = False,
) -> FastAPI:
    """The gateway app as __main__ builds it, on the tenant's registry. `opa` defaults to an address nothing answers,
    for tests that never reach a decision; `upstream` is what http operations call. `mcp` serves /mcp: its SDK manager
    runs a task group that must be left in the task that entered it, so a test using it enters the lifespan itself,
    never in a fixture whose teardown runs in another task."""
    settings = Settings()
    catalog = load_catalog(AGENTS_FIXTURES)
    directory = Directory.from_seed(seed, datetime.now(UTC))
    store, calls = ModuleStore(engine), CallLog(engine)
    policy = EgressPolicy(EgressStore(engine))
    cipher = AesGcmCipher(settings.secrets_key.get_secret_value())
    resolver = SecretResolver(SecretStore(engine), cipher)
    connections = ConnectionStore(engine)
    tokens = Tokens(connections, cipher, upstream, policy)
    authenticator = Authenticator(connections, resolver, tokens, directory.wide_teams)
    service = ModuleService(
        store,
        directory,
        calls,
        egress=policy,
        http=upstream,
        secrets=resolver,
        workflows=workflows or StaticWorkflows(seed.get("workflows", [])),
        reviews=reviews or FakeReviews(),
        publish_policy=publish_policy,
        auth=authenticator,
    )
    return create_gateway_app(
        opa=OpaClient(opa or httpx.AsyncClient(base_url="http://opa.invalid")),
        registry=ToolRegistry(catalog, store),
        log=calls,
        runner=LocalToolRunner(catalog, MemorySender(), cases=cases, decisions=service),
        review_key=REVIEW_KEY,
        auth=auth or test_auth(settings, tenant, seed["currentUser"], dev=dev),
        routers=(
            modules_router(service, directory),
            executions_router(service, directory),
            egress_router(EgressStore(engine)),
            secrets_router(SecretStore(engine), cipher, modules=ModuleStore(engine)),
            send_policy_router(SendPolicies(engine), directory),
            mocks_router(MockStore(engine), ModuleStore(engine), directory, security_team="team_security"),
            connections_router(
                ConnectionService(
                    connections,
                    SecretStore(engine),
                    cipher,
                    tokens,
                    directory,
                    egress=policy,
                    console_url=CONSOLE_URL,
                    discovery=Discovery(upstream, policy) if upstream is not None else None,
                ),
                directory,
            ),
        ),
        http_client=upstream,
        egress=policy,
        secret_resolver=resolver,
        write_approvals=write_approvals,
        send_check=send_check,
        authenticator=authenticator,
        directory=directory if mcp else None,
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
        opa_client() as opa,
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
