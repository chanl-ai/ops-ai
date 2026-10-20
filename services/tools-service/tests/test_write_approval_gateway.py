"""Which writes wait for approval at the gateway (c-219), by failure mode: open_case, declared to run at once, still
refused without a token; a write that waits let through without one; a caller saying in its request that its write
needs no approval; and a team that has every write wait (toolWritesNeedApproval) letting open_case through. Decided by
the real Rego in OPA, on a seeded tenant's registry."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.modules.policy import WriteApprovals
from ops_tools.modules.seed import load
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, opa_client, service_headers

CASE = {"subject": "Card stopped working abroad"}
ADDRESS = {
    "customerId": "CUS-1001",
    "line1": "12 Harbour Street",
    "city": "Halifax",
    "province": "NS",
    "postalCode": "B3J 1A1",
}


class EveryWriteWaits(WriteApprovals):
    """The team turned toolWritesNeedApproval on, as the live read answers it."""

    def __init__(self) -> None:
        super().__init__(cast(Any, None))

    async def all_writes(self, tenant_id: str, team_id: str | None) -> bool:
        return bool(tenant_id)


Call = Callable[..., Any]


async def _gateway(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog: list[dict[str, Any]], approvals: Any
) -> AsyncIterator[Call]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog)
    async with opa_client() as opa:
        app = build_app(engine, seed, tenant, opa=opa, write_approvals=approvals)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as client,
        ):

            async def call(tool: str, args: dict[str, Any], key: str, **extra: Any) -> httpx.Response:
                body = {"tool": tool, "input": args, "key": key, "runContext": {"act": "test"}, **extra}
                return await client.post("/v1/calls", json=body, headers=service_headers(tenant))

            yield call


@pytest.fixture
async def gateway(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Call]:
    async for call in _gateway(engine, seed, tenant, catalog_tools, None):
        yield call


@pytest.fixture
async def strict(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Call]:
    async for call in _gateway(engine, seed, tenant, catalog_tools, EveryWriteWaits()):
        yield call


def reasons(r: httpx.Response) -> list[str]:
    return list(r.json()["error"]["details"]["reasons"])


async def test_open_case_needs_no_token_and_a_write_that_waits_still_does(gateway: Call) -> None:
    opened = await gateway("open_case", CASE, "s1")
    # Allowed by the policy; with no agents-service behind this runner the case itself is not opened.
    assert opened.json()["data"]["decision"] == "allow", opened.text
    refused = await gateway("update_address", ADDRESS, "s2")
    assert (refused.status_code, reasons(refused)) == (403, ["write needs an approval token"]), refused.text


async def test_a_caller_cannot_say_its_write_needs_no_approval(gateway: Call) -> None:
    r = await gateway("update_address", ADDRESS, "s3", approvalRequired=False)
    assert (r.status_code, r.json()["error"]["code"]) == (400, "validation_failed"), r.text


async def test_a_team_that_has_every_write_wait_refuses_open_case_without_a_token(strict: Call) -> None:
    r = await strict("open_case", CASE, "s4")
    assert (r.status_code, reasons(r)) == (403, ["write needs an approval token"]), r.text
