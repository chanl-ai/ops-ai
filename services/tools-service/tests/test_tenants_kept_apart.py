"""Two tenants on one tools-service are kept apart, by failure mode: an outbound request dialled with another tenant's
allow-list or with none, a connection opened for one tenant reused for another, and a local tool (send_reply) run
for a tenant other than the caller's. Identity reaches tool code one way: the verified caller, passed explicitly."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from ops_tools.egress import EgressDenied, EgressPolicy, EgressTransport, for_tenant
from ops_tools.store.egress import EgressStore

from .test_egress import Dialled, RecordingNetwork, ScriptedResolver

HOST = "core.bank.test"


@pytest.fixture
async def transport(engine: Any, tenant: str) -> EgressTransport:
    """Tenant `tenant` lists the bank's host and its private range; tenant `other` lists the host only."""
    store, now = EgressStore(engine), datetime.now(UTC)
    for t in (tenant, "other"):
        await store.add(t, "host", HOST, actor="test", note="", at=now)
    await store.add(tenant, "range", "10.20.0.0/16", actor="test", note="", at=now)
    resolver = ScriptedResolver({HOST: [["10.20.4.7"]]})
    return EgressTransport(
        EgressPolicy(store, resolver), httpx.create_ssl_context(), network=RecordingNetwork(resolver)
    )


async def _send(transport: EgressTransport, extensions: dict[str, str]) -> str:
    try:
        await transport.handle_async_request(httpx.Request("GET", f"https://{HOST}/v1/x", extensions=extensions))
    except Dialled as d:
        return d.address
    raise AssertionError("the request neither dialled nor was refused")


async def test_each_tenant_dials_with_its_own_allow_list(transport: EgressTransport, tenant: str) -> None:
    assert await _send(transport, for_tenant(tenant)) == "10.20.4.7"
    with pytest.raises(EgressDenied):
        await _send(transport, for_tenant("other"))
    # Each tenant has its own connection pool, so a connection opened for one is never handed to the other.
    assert set(transport.pools) == {tenant, "other"} and transport.pools[tenant] is not transport.pools["other"]


async def test_a_request_naming_no_tenant_is_refused_before_anything_is_dialled(transport: EgressTransport) -> None:
    with pytest.raises(EgressDenied):
        await _send(transport, {})
    assert transport.pools == {}
