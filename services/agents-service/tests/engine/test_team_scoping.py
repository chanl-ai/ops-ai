"""v2 workflows and runs are scoped to the selected team as v1's are (dev selects none and sees all): another team's
workflow is not listed, read, started or deleted, and its run is not found."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api.auth import Principal
from ops_agents.api.routers.engine import visible_run
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import current_tenant, tenant_scope
from ops_engine.store import DefinitionStore, RunStore, WorkflowOwnedError
from ops_service_kit.errors import NotFound
from ops_store import isolation

# The dev header caller, which decides for any team.
B = Principal(name="b@x", email="b@x", team_id="team_ops", tenant_id="local", team_ids=("team_ops",), dev=True)


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def test_another_teams_workflow_and_run_are_not_found(engine: AsyncEngine) -> None:
    tx, wf = EngineTransactions(engine), f"wf_{uuid4().hex[:8]}"
    store = DefinitionStore(tx)
    with tenant_scope(f"t-{uuid4().hex[:6]}"):
        await store.publish(
            wf, name="W", definition={}, digest="d" * 64, now="n", by="a", team="team_cards", stage="live"
        )
        rid = f"wfrun_{uuid4().hex[:10]}"
        row: dict[str, Any] = {"id": rid, "team_id": "team_cards", "workflow_id": wf, "version": 1, "digest": "d" * 64}
        await RunStore(tx).create(row | {"run_key": rid, "mode": "live", "input": {}, "created_by": "a"})
        assert wf not in [d["workflow_id"] for d in await store.summaries(team="team_lending")]
        assert await store.get(wf, team="team_lending") is None
        assert await store.delete_draft(wf, team="team_lending") == "missing"
        assert await store.get(wf, team="team_cards") is not None
        rt: Any = SimpleNamespace(db=engine)
        with isolation.scope(current_tenant(), "team_lending"), pytest.raises(NotFound):
            await visible_run(rt, rid)
        with isolation.scope(current_tenant(), "team_cards"):
            assert (await visible_run(rt, rid))["id"] == rid


async def test_another_teams_review_cannot_be_read_or_decided(engine: AsyncEngine) -> None:
    from ops_agents.api import engine_reviews  # noqa: PLC0415

    tx, wf, rid = EngineTransactions(engine), f"wf_{uuid4().hex[:8]}", f"wfrun_{uuid4().hex[:10]}"
    with tenant_scope(f"t-{uuid4().hex[:6]}"):
        await DefinitionStore(tx).publish(
            wf, name="W", definition={}, digest="d" * 64, now="n", by="a", team="team_cards", stage="live"
        )
        row: dict[str, Any] = {"id": rid, "team_id": "team_cards", "workflow_id": wf, "version": 1, "digest": "d" * 64}
        await RunStore(tx).create(row | {"run_key": rid, "mode": "live", "input": {}, "created_by": "a"})
        payload = {"node": "review", "step_id": f"{rid}:review:1", "iteration": 1}
        waiting = {"node": "review", "iteration": 1, "interruptId": "i", "payload": payload}
        await RunStore(tx).update(rid, status="waiting", waiting=waiting)
        rt: Any = SimpleNamespace(db=engine, settings=SimpleNamespace(lease_ttl_seconds=6.0))
        with isolation.scope(current_tenant(), "team_lending"):
            with pytest.raises(NotFound):
                await engine_reviews.get(rt, rid)
            with pytest.raises(NotFound):
                await engine_reviews.decide(rt, B, rid, decision="rejected", reason=None)
            assert [r for r in await engine_reviews.all_rows(rt) if r["id"].startswith(rid)] == []
        assert (await RunStore(tx).get(rid) or {})["status"] == "waiting", "the other team's decision changed nothing"


async def test_another_team_cannot_publish_over_a_workflow_id(engine: AsyncEngine) -> None:
    tx, wf = EngineTransactions(engine), f"wf_{uuid4().hex[:8]}"
    store = DefinitionStore(tx)
    with tenant_scope(f"t-{uuid4().hex[:6]}"):
        await store.publish(wf, name="A", definition={}, digest="a" * 64, now="n", by="a", team="team_cards")
        with pytest.raises(WorkflowOwnedError):
            await store.publish(wf, name="B", definition={}, digest="b" * 64, now="n", by="b", team="team_lending")
        mine = [d for d in await store.summaries(team="team_cards") if d["workflow_id"] == wf]
        assert [(d["name"], d["version"]) for d in mine] == [("A", 1)]
