"""E2c: a takeover raises tools-service's fence before the new owner resumes, so a stalled old owner's tool write
cannot land between the takeover and the new owner's first tool write."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.activities.gateway import GatewayClient
from ops_agents.api.fencing import ToolsFence
from ops_agents.store.graphs import GraphStore
from ops_agents.store.leases import Leases
from ops_identity import ServiceClient, dev_service_signer
from ops_service_kit.ids import now_iso

from .conftest import Gateway

pytestmark = pytest.mark.usefixtures("local_tenant")

DOC = {"customerId": "C-1042", "document": "proof of address", "reason": "Address changed last week."}
TTL = 0.5


async def write(gateway: Gateway, generation: int, step: str) -> httpx.Response:
    """A request_document write on the thread with an approval token, as the run of `generation` would send it."""
    token = gateway.token("request_document", DOC, step=step, approvers=["dana@bank.test"])
    return await gateway.client.post(
        "/v1/calls",
        headers={"X-Lease-Generation": str(generation)},
        json={
            "tool": "request_document",
            "input": DOC,
            "key": step,
            "runContext": {"thread": gateway.thread, "step": step, "act": "test"},
            "approvalToken": token,
        },
    )


async def thread_row(engine: AsyncEngine, thread_id: str) -> GraphStore:
    store = GraphStore(engine)
    await store.create_thread(thread_id, "complex_workflow", {}, "team", now_iso())
    return store


def fence(gateway: Gateway, engine: AsyncEngine, client: httpx.AsyncClient | None = None) -> ToolsFence:
    gc = GatewayClient(
        ServiceClient(client or gateway.client, dev_service_signer(), "agents", "tools", tenant=lambda: "local")
    )
    return ToolsFence(gc, GraphStore(engine))


async def take_over(engine: AsyncEngine, thread_id: str, hook: Any) -> int:
    """Owner A takes the lease and stalls past its TTL; owner B takes it over."""
    a = Leases(engine, owner="owner-a", ttl=TTL)
    await a.acquire(thread_id, "run_a")
    await asyncio.sleep(TTL + 0.2)
    b = Leases(engine, owner="owner-b", ttl=30, on_takeover=hook)
    return await b.acquire(thread_id, "run_b")


async def test_stale_owner_write_after_takeover_is_refused(gateway: Gateway, engine: AsyncEngine) -> None:
    await thread_row(engine, gateway.thread)
    a = Leases(engine, owner="owner-a", ttl=TTL)
    old = await a.acquire(gateway.thread, "run_a")
    assert (await write(gateway, old, "s1")).status_code == 200
    await asyncio.sleep(TTL + 0.2)
    b = Leases(engine, owner="owner-b", ttl=30, on_takeover=fence(gateway, engine))
    new = await b.acquire(gateway.thread, "run_b")
    assert new == old + 1
    # Owner A wakes up and writes before owner B has made any tool write.
    stale = await write(gateway, old, "s2")
    assert stale.status_code == 409
    assert stale.json()["error"]["details"]["reasons"] == ["lease superseded"]


async def test_fence_call_is_idempotent_and_refuses_a_lower_generation(gateway: Gateway) -> None:
    body = {"thread": gateway.thread, "generation": 3}
    first = await gateway.client.post("/v1/fences", json=body)
    again = await gateway.client.post("/v1/fences", json=body)
    assert (first.status_code, again.status_code) == (200, 200)
    assert again.json()["data"]["generation"] == 3
    lower = await gateway.client.post("/v1/fences", json={**body, "generation": 2})
    assert lower.status_code == 409
    assert (await gateway.client.post("/v1/fences", json=body, headers={"Authorization": ""})).status_code == 401


async def test_takeover_goes_on_when_tools_service_is_down(gateway: Gateway, engine: AsyncEngine) -> None:
    store = await thread_row(engine, gateway.thread)
    async with httpx.AsyncClient(base_url="http://127.0.0.1:9", timeout=1) as down:
        new = await take_over(engine, gateway.thread, fence(gateway, engine, down))
    runs = await store.runs(gateway.thread)
    warnings = [e["event"] for r in runs if r["kind"] == "lease" for e in r["events"]]
    assert warnings == ["lease.fence_not_raised"]
    # The new owner's first tool write raises the fence itself; after it the old generation is refused.
    assert (await write(gateway, new, "s1")).status_code == 200
    assert (await write(gateway, new - 1, "s2")).status_code == 409


async def test_a_finished_run_is_not_a_takeover(gateway: Gateway, engine: AsyncEngine) -> None:
    calls: list[tuple[str, int]] = []

    async def hook(thread_id: str, generation: int) -> None:
        calls.append((thread_id, generation))

    leases = Leases(engine, owner="owner-a", ttl=30, on_takeover=hook)
    await leases.acquire(gateway.thread, "run_1")
    await leases.release(gateway.thread, "run_1")
    await leases.acquire(gateway.thread, "run_2")
    assert calls == []
