"""The gateway in-process on the compose PostgreSQL and OPA (`make db-up`), with the seed catalogue's tools."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.activities.catalog import load_catalog
from ops_email import MemorySender
from ops_identity import dev_service_signer, mint_service_token
from ops_service_kit import opa_server
from ops_service_kit.ids import input_hash, new_id
from ops_service_kit.settings import Settings
from ops_tools.app import create_gateway_app
from ops_tools.opa import OpaClient
from ops_tools.registry import ToolRegistry
from ops_tools.store import CallLog
from ops_tools.tokens import Binding, mint
from ops_tools.tools import LocalToolRunner

ROOT = Path(__file__).parents[2]
SEED = ROOT / "tests" / "fixtures" / "seed"
# This process's own OPA, never the shared one on :8181, whose key and policy any tools-service start rewrites.
OPA_URL = opa_server.session_url()
REVIEW_KEY = "test-review-key"
# agents-service's Ed25519 token for tools-service (dev key, dev only), naming the tenant it calls for; the gateway
# takes the caller from it. Minted per request so a long session never sends an expired one.
SUB = "service:agents"


def service_token(service: str = "agents") -> str:
    return mint_service_token(dev_service_signer(), service=service, audience="tools", tenant_id="local")


class ServiceAuthHeader(httpx.Auth):
    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response]:
        request.headers.setdefault("Authorization", f"Bearer {service_token()}")
        yield request


@pytest.fixture(scope="session")
def gateway_db_url() -> str:
    url = Settings().database_url
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    return url


@pytest.fixture
async def engine(gateway_db_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(gateway_db_url)
    yield e
    await e.dispose()


@dataclass
class Clock:
    """The gateway's clock, which judges token expiry; `at` fixes it, None follows the real time."""

    at: float | None = None

    def read(self) -> float:
        return self.at if self.at is not None else time.time()


@dataclass
class Decisions:
    """tools-service's modules, as the gateway's apply_tool_access reaches them (c-257): records each decision."""

    applied: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    async def apply_access_decision(self, tenant_id: str, module_id: str, **kw: Any) -> dict[str, Any]:
        self.applied.append({"tenant_id": tenant_id, "module_id": module_id, **kw})
        return {"id": kw["approval_id"], "status": "approved" if kw["decision"] == "approved" else "rejected"}


@dataclass
class Gateway:
    client: httpx.AsyncClient
    log: CallLog
    thread: str
    clock: Clock = field(default_factory=Clock)
    # What send_reply sent: the gateway's runner sends through this sender.
    mail: MemorySender = field(default_factory=MemorySender)
    decisions: Decisions = field(default_factory=Decisions)

    async def call(
        self,
        tool: str,
        args: dict[str, Any],
        *,
        step: str,
        token: str | None = None,
        thread: str | None = None,
        service: str = "agents",
    ) -> httpx.Response:
        """`service` is who the service token names: the gateway takes the caller from it, not from the body."""
        return await self.client.post(
            "/v1/calls",
            headers={"Authorization": f"Bearer {service_token(service)}"},
            json={
                "tool": tool,
                "input": args,
                "key": step,
                "runContext": {"thread": thread or self.thread, "step": step, "act": "test"},
                "approvalToken": token,
            },
        )

    def token(
        self,
        tool: str,
        args: dict[str, Any],
        *,
        step: str,
        approvers: list[str],
        ttl_s: int = 300,
        thread: str | None = None,
        key: str = REVIEW_KEY,
        now: float | None = None,
    ) -> str:
        binding = Binding(thread or self.thread, step, tool, input_hash(args), approvers)
        return mint(binding, key, ttl_s=ttl_s, now=now)


@pytest.fixture
async def gateway(engine: AsyncEngine) -> AsyncIterator[Gateway]:
    async with httpx.AsyncClient(base_url=OPA_URL) as opa_http:
        log = CallLog(engine)
        clock = Clock()
        mail = MemorySender()
        decisions = Decisions()
        app = create_gateway_app(
            clock=clock.read,
            opa=OpaClient(opa_http),
            registry=ToolRegistry(load_catalog(SEED)),
            log=log,
            runner=LocalToolRunner(load_catalog(SEED), mail, decisions=decisions),
            review_key=REVIEW_KEY,
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway", auth=ServiceAuthHeader()
            ) as client,
        ):
            yield Gateway(client, log, new_id("gth"), clock, mail, decisions)
