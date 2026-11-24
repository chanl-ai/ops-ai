"""A person approving their own write, by failure mode: the session token was minted while the person held Approvals
decide, an admin unticked the cell, and the gateway still let that person's no-token write through on the token's copy.
The cell is asked of platform-service at the call, so the same token no longer self-approves."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.modules.policy import OwnRequests
from ops_tools.modules.seed import load
from ops_tools.store.egress import EgressStore
from ops_tools.store.modules import Module, ModuleStore

from .conftest import build_app, opa_client
from .fake_upstream import ENDPOINT, HOST, SlowAware, fake_bank
from .test_apply_tool_access import Platform
from .test_calls import Gateway, bank_module, on_its_connection
from .test_test_run_writes import _on_accounts, _real  # pyright: ignore[reportPrivateUsage]
from .test_write_approval_gateway import TeamAsksReviewer


@pytest.fixture
async def stale_token_gateway(
    engine: AsyncEngine,
    seed: dict[str, Any],
    tenant: str,
    catalog_tools: list[dict[str, Any]],
) -> AsyncIterator[Gateway]:
    """The dev person's token holds every cell, as one minted before the change would, while the gateway's live check
    says the cell is unticked. The team has ask before changes on: with it off a write never waits."""
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    module = await on_its_connection(engine, bank_module(tenant, "livepol"), ENDPOINT)
    await EgressStore(engine).add(tenant, "host", HOST, actor="test", note="", at=datetime.now(UTC))
    await ModuleStore(engine).put(cast(Module, module), expected_revision=None)
    bank, received = fake_bank()
    async with (
        opa_client() as opa,
        httpx.AsyncClient(transport=SlowAware(httpx.ASGITransport(app=bank))) as upstream,
    ):
        app = build_app(
            engine,
            seed,
            tenant,
            opa=opa,
            upstream=upstream,
            # platform-service's access check after an admin unticked Approvals decide for the person.
            own_requests=OwnRequests(cast(Any, Platform(set()))),
            write_approvals=TeamAsksReviewer(),
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as client,
        ):
            yield Gateway(client, received, "livepol", "gth_live", tenant)


async def test_a_token_minted_while_self_approval_was_on_no_longer_self_approves(
    stale_token_gateway: Gateway, engine: AsyncEngine
) -> None:
    g = stale_token_gateway
    await _on_accounts(g, engine, test_account=False)
    out = await _real(g, "live")  # the person's own live write, with nobody else approving
    assert out["decision"] != "allow", f"self-approved on a stale token: {out}"
    assert not [r for r in g.received if r["path"] == "/v1/holds"], "the write reached the bank unapproved"


async def test_with_no_platform_service_an_asker_never_decides_their_own_request() -> None:
    """No platform client means the cell cannot be asked, so the gateway refuses as the module service does: a check
    that cannot be made never lets someone approve their own request."""
    refused = await OwnRequests(None).refusal("tenant_a", "team_a", "ana@example.com", ["ana@example.com"])
    assert refused is not None and refused.code == "own_request", refused
    assert await OwnRequests(None).refusal("tenant_a", "team_a", "ana@example.com", ["ben@example.com"]) is None
