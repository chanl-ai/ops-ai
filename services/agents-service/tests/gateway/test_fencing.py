"""E2b fencing at the gateway: the current owner's write goes through and raises the thread's fence; a stalled owner's
write with the older generation (X-Lease-Generation header) is refused before OPA and the dedup claim, and so is a
write with no generation on a fenced thread."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.store.leases import Leases, db_now, thread_leases
from tests.gateway.conftest import Gateway

ARGS = {"wireId": "W-88213", "hours": 24, "reason": "New payee"}


async def write(gateway: Gateway, token: str, generation: int | None) -> Any:
    headers = {"X-Lease-Generation": str(generation)} if generation is not None else {}
    return await gateway.client.post(
        "/v1/calls",
        headers=headers,
        json={
            "tool": "place_wire_hold",
            "input": ARGS,
            "key": "s1",
            "approvalToken": token,
            "runContext": {"thread": gateway.thread, "step": "s1", "act": "test"},
        },
    )


async def test_stale_generation_write_is_refused(gateway: Gateway, engine: AsyncEngine) -> None:
    a, b = Leases(engine, "proc-a", ttl=30), Leases(engine, "proc-b", ttl=30)
    gen_a = await a.acquire(gateway.thread, "run_a")
    async with engine.begin() as c:
        await c.execute(
            thread_leases.update()
            .where(thread_leases.c.thread_id == gateway.thread)
            .values(expires_at=db_now(engine) - 1)
        )
    gen_b = await b.acquire(gateway.thread, "run_b")
    token = gateway.token("place_wire_hold", ARGS, step="s1", approvers=["Maya Okafor", "Daniel Brooks"])

    current = await write(gateway, token, gen_b)
    assert current.status_code == 200, current.text
    assert current.json()["data"]["ok"] is True

    # A wakes and sends the same approved write: refused before OPA and the dedup claim, not replayed.
    stale = await write(gateway, token, gen_a)
    assert stale.status_code == 409, stale.text
    assert stale.json()["error"]["details"]["reasons"] == ["lease superseded"]

    unfenced = await write(gateway, token, None)
    assert unfenced.status_code == 409 and unfenced.json()["error"]["details"]["reasons"] == ["lease superseded"]
