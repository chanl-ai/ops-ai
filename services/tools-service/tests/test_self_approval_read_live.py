"""A person approving their own write, by failure mode: the session token was minted while requesterMayDecide was on,
a team admin turned it off, and the gateway still let that person's no-token write through on the token's copy of the
policy. The setting is read at the call, so the same token no longer self-approves."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.modules.seed import load
from ops_tools.store.egress import EgressStore
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, opa_client
from .fake_upstream import ENDPOINT, HOST, SlowAware, fake_bank
from .test_calls import Gateway, bank_module, on_its_connection
from .test_test_run_writes import _on_accounts, _real  # pyright: ignore[reportPrivateUsage]


class PolicyNowOff:
    """requesterMayDecide as the live read answers it after an admin turned it off."""

    async def allowed(self, tenant_id: str) -> bool:
        return False


@pytest.fixture
async def stale_token_gateway(
    monkeypatch: pytest.MonkeyPatch,
    engine: AsyncEngine,
    seed: dict[str, Any],
    tenant: str,
    catalog_tools: list[dict[str, Any]],
) -> AsyncIterator[Gateway]:
    """The dev person's token carries requesterMayDecide=true, as one minted before the change would, while the
    gateway's live read says off."""
    monkeypatch.setenv("OPS_DEV_POLICIES", '{"requesterMayDecide": true}')
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    module = await on_its_connection(engine, bank_module(tenant, "livepol"), ENDPOINT)
    await EgressStore(engine).add(tenant, "host", HOST, actor="test", note="", at=datetime.now(UTC))
    await ModuleStore(engine).put(module, expected_revision=None)
    bank, received = fake_bank()
    async with (
        opa_client() as opa,
        httpx.AsyncClient(transport=SlowAware(httpx.ASGITransport(app=bank))) as upstream,
    ):
        app = build_app(engine, seed, tenant, opa=opa, upstream=upstream, requester_policy=PolicyNowOff())
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
    assert out["decision"] != "allow", f"self-approved on a stale token policy: {out}"
    assert not [r for r in g.received if r["path"] == "/v1/holds"], "the write reached the bank unapproved"
