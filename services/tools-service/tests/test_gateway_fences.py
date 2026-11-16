"""A thread's write fence, by failure mode: a lower generation lowers the fence; a stalled owner's write (a generation
below the fence, or none on a fenced thread) is claimed instead of refused; and one tenant reads or raises another
tenant's fence on a thread id they both use, so its writes are refused or let through by the other's runs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import new_id
from ops_store import isolation
from ops_tools.store import CallLog
from ops_tools.store.calls import LeaseSupersededError

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


async def test_the_fence_only_rises_and_refuses_a_stalled_owners_write(engine: AsyncEngine, tenant: str) -> None:
    log, thread = CallLog(engine), f"thr_{uuid4().hex[:10]}"
    with isolation.scope(tenant, TEAM):
        assert await log.raise_fence(tenant, thread, 3) == 3
        assert await log.raise_fence(tenant, thread, 2) == 3, "a lower generation lowered the fence"
        assert await log.raise_fence(tenant, thread, 5) == 5
        with pytest.raises(LeaseSupersededError):
            await log.claim(generation=4, **_write(tenant, thread))
        with pytest.raises(LeaseSupersededError):
            await log.claim(generation=None, **_write(tenant, thread))


async def test_a_tenant_neither_reads_nor_raises_another_tenants_fence(engine: AsyncEngine, tenant: str) -> None:
    log, thread, other = CallLog(engine), f"thr_{uuid4().hex[:10]}", f"t_{uuid4().hex[:10]}"
    with isolation.scope(tenant, TEAM):
        assert await log.raise_fence(tenant, thread, 5) == 5
    with isolation.scope(other, TEAM):
        assert await log.raise_fence(other, thread, 1) == 1, "the other tenant read this tenant's fence"
        assert await log.raise_fence(other, thread, 9) == 9
    with isolation.scope(tenant, TEAM):
        assert await log.raise_fence(tenant, thread, 1) == 5, "the other tenant raised this tenant's fence"
