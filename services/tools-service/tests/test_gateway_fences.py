"""A thread's write fence, by failure mode: a lower generation lowers the fence; a stalled owner's write (a generation
below the fence, or none on a fenced thread) is claimed instead of refused; and one tenant reads or raises another
tenant's fence on a thread id they both use, so its writes are refused or let through by the other's runs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.contract import response_checker
from ops_service_kit.ids import new_id
from ops_store import isolation
from ops_tools.store import CallLog
from ops_tools.store.calls import LeaseSupersededError

from .conftest import build_app, service_headers

TEAM = "team_platform"


def _write(tenant: str, thread: str) -> dict[str, Any]:
    key = f"{thread}:step:1:1"
    return {
        "id": new_id("call"),
        "tenant_id": tenant,
        "team_id": TEAM,
        "tool": "place_hold",
        "access": "write",
        "input_hash": "h",
        "idempotency_key": key,
        "thread_id": thread,
        "step": key,
        "sub": "service:agents",
        "act": "graph",
        "approvers": [],
        "created_at": datetime.now(UTC).isoformat(),
        "module_id": "mod_core_banking",
        "approval_token_id": None,
        "decision": "allow",
        "reasons": [],
    }


async def test_the_fence_only_rises_and_refuses_a_stalled_owners_write(both_engine: AsyncEngine, tenant: str) -> None:
    engine = both_engine
    log, thread = CallLog(engine), f"thr_{uuid4().hex[:10]}"
    with isolation.scope(tenant, TEAM):
        assert await log.raise_fence(tenant, thread, 3) == 3
        assert await log.raise_fence(tenant, thread, 2) == 3, "a lower generation lowered the fence"
        assert await log.raise_fence(tenant, thread, 5) == 5
        with pytest.raises(LeaseSupersededError):
            await log.claim(generation=4, **_write(tenant, thread))
        with pytest.raises(LeaseSupersededError):
            await log.claim(generation=None, **_write(tenant, thread))


async def test_a_tenant_neither_reads_nor_raises_another_tenants_fence(both_engine: AsyncEngine, tenant: str) -> None:
    engine = both_engine
    log, thread, other = CallLog(engine), f"thr_{uuid4().hex[:10]}", f"t_{uuid4().hex[:10]}"
    with isolation.scope(tenant, TEAM):
        assert await log.raise_fence(tenant, thread, 5) == 5
    with isolation.scope(other, TEAM):
        assert await log.raise_fence(other, thread, 1) == 1, "the other tenant read this tenant's fence"
        assert await log.raise_fence(other, thread, 9) == 9
    with isolation.scope(tenant, TEAM):
        assert await log.raise_fence(tenant, thread, 1) == 5, "the other tenant raised this tenant's fence"


async def test_the_fence_route_raises_the_callers_tenants_fence_and_refuses_a_lower_one(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str
) -> None:
    # Every reply, the 409 included, is checked against openapi.json's schemas.
    app = build_app(engine, seed, tenant, dev=True)
    fence = {"thread": f"thr_{uuid4().hex[:10]}", "generation": 4}
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        raised = await c.post("/v1/fences", json=fence, headers=service_headers(tenant))
        assert raised.status_code == 200 and raised.json()["data"] == fence, raised.text
        lower = await c.post("/v1/fences", json={**fence, "generation": 2}, headers=service_headers(tenant))
        assert lower.status_code == 409 and lower.json()["error"]["code"] == "lease_superseded", lower.text
        other = {**fence, "generation": 2}
        elsewhere = await c.post("/v1/fences", json=other, headers=service_headers(f"t_{uuid4().hex[:10]}"))
        assert elsewhere.status_code == 200, "another tenant's fence on the same thread id refused this one"
