"""The dev seed keeps the approval answer migration 0074 gave each seeded write, by failure mode: a reseed (every
dev start replaces each unedited seeded module) writing the declared requiresApproval but no approval_mode, so
transfer_funds and the other seeded writes stop waiting for a reviewer on a fresh or reseeded database."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.modules.seed import load
from ops_tools.store.modules import ModuleStore, module_operations


async def test_a_reseed_leaves_every_seeded_write_that_declares_a_wait_answering_reviewer(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> None:
    for _ in range(2):
        await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    o = module_operations.c
    q = sa.select(o.name, o.approval_mode).where(
        o.tenant_id == tenant, o.access == "write", o.requires_approval.is_(True)
    )
    async with engine.connect() as c:
        rows = [(r[0], r[1]) for r in await c.execute(q)]
    assert rows, "the seed holds writes that declare a wait"
    assert [r for r in rows if r[1] != "reviewer"] == []
