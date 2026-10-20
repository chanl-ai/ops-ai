"""A parent waiting at Run workflow wakes as its children end (c-263), by failure mode: two children ending at the same
moment wake the parent twice for one change, or a child's end wakes nothing so the parent waits for ever; a parent that
is not waiting on its children is woken anyway."""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import RunStore
from ops_engine.store.tables import engine_runs, engine_work
from tests.engine.test_worker import engine  # noqa: F401  # pyright: ignore[reportUnusedImport]

AT = "2026-10-19T00:00:00+00:00"


async def seed(tx: EngineTransactions, parent: str, children: list[str], waits_on: str | None) -> None:
    payload = {"kind": waits_on, "node": "read", "iteration": 1} if waits_on else {"kind": "review", "node": "check"}
    rows = [
        {
            "id": parent,
            "status": "waiting",
            "created_by": "a@x",
            "waiting": {"node": payload["node"], "iteration": 1, "interruptId": "i1", "payload": payload},
        },
        *({"id": c, "status": "running", "created_by": f"run:{parent}", "waiting": None} for c in children),
    ]
    async with tx.tenant_tx() as c:
        await c.execute(
            engine_runs.insert(),
            [
                {
                    **r,
                    "tenant_id": tx.tenant(),
                    "team_id": "team_ops",
                    "workflow_id": "wf",
                    "version": 1,
                    "digest": "d",
                    "run_key": f"k:{r['id']}",
                    "mode": "live",
                    "created_at": AT,
                    "updated_at": AT,
                }
                for r in rows
            ],
        )


async def wakes(tx: EngineTransactions, parent: str) -> list[str]:
    async with tx.tenant_tx() as c:
        q = sa.select(engine_work.c.dedupe_key).where(engine_work.c.run_id == parent, engine_work.c.kind == "resume")
        return sorted(str(k) for k in (await c.execute(q)).scalars())


async def woken_pauses(tx: EngineTransactions, parent: str) -> set[str]:
    """The interrupt ids the parent's wakes name: the worker resumes only the pause a wake was queued for."""
    async with tx.tenant_tx() as c:
        q = sa.select(engine_work.c.payload).where(engine_work.c.run_id == parent, engine_work.c.kind == "resume")
        return {str(p.get("interruptId")) for p in (await c.execute(q)).scalars()}


async def test_each_childs_end_wakes_its_waiting_parent_once(engine: AsyncEngine) -> None:  # noqa: F811
    tx = EngineTransactions(engine)
    store = RunStore(tx)
    u = uuid4().hex[:8]
    parent, a, b = f"wfrun_p{u}", f"wfrun_a{u}", f"wfrun_b{u}"
    with tenant_scope(f"t_{u}"):
        await seed(tx, parent, [a, b], "children")
        for child in (a, b):
            await store.update(child, status="succeeded")
        # Both children ended together; each worker settles, and one settles twice.
        for child in (a, b, a):
            run = await store.get(child)
            assert run is not None
            await store.settle_parents(run)
        found = await wakes(tx, parent)
        pauses = await woken_pauses(tx, parent)
    assert found == [f"children:{parent}:{a}:succeeded", f"children:{parent}:{b}:succeeded"], found
    assert pauses == {"i1"}, pauses


async def test_a_parent_waiting_on_a_person_is_not_woken_by_a_child(engine: AsyncEngine) -> None:  # noqa: F811
    tx = EngineTransactions(engine)
    store = RunStore(tx)
    u = uuid4().hex[:8]
    parent, a = f"wfrun_p{u}", f"wfrun_a{u}"
    with tenant_scope(f"t_{u}"):
        await seed(tx, parent, [a], None)
        await store.update(a, status="succeeded")
        run = await store.get(a)
        assert run is not None
        await store.settle_parents(run)
        assert await wakes(tx, parent) == []


async def test_children_read_in_item_order_on_the_parent_index(engine: AsyncEngine) -> None:  # noqa: F811
    tx = EngineTransactions(engine)
    u = uuid4().hex[:8]
    parent = f"wfrun_p{u}"
    with tenant_scope(f"t_{u}"):
        await seed(tx, parent, [], "children")
        async with tx.tenant_tx() as c:
            for i in (2, 0, 1):
                await c.execute(
                    engine_runs.insert().values(
                        id=f"wfrun_c{i}{u}",
                        tenant_id=tx.tenant(),
                        team_id="team_ops",
                        workflow_id="wf",
                        version=1,
                        digest="d",
                        run_key=f"child:{parent}:read:1:{i}",
                        mode="live",
                        status="succeeded" if i else "running",
                        created_by=f"run:{parent}",
                        created_at=AT,
                        updated_at=AT,
                    )
                )
        found = await RunStore(tx).children(parent, f"child:{parent}:read:1:")
    assert [(c["index"], c["runId"], c["status"]) for c in found] == [
        (0, f"wfrun_c0{u}", "running"),
        (1, f"wfrun_c1{u}", "succeeded"),
        (2, f"wfrun_c2{u}", "succeeded"),
    ]
