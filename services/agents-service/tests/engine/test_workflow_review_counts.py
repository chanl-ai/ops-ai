"""The Workflows list's "sent to review" and open-review counts, by failure mode: a run that opened no Human Task
counted; a run older than the 24h window counted; open tasks not counted; another team's runs counted."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.journal import StepRow, StepStatus
from ops_engine.store import DefinitionStore, RunStore
from ops_engine.store.steps import SqlJournal
from ops_engine.store.tables import engine_runs

CUTOFF = (datetime.now(UTC) - timedelta(days=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
OLD = "2020-01-01T00:00:00.000Z"


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def run_with(
    tx: EngineTransactions,
    wf: str,
    team: str,
    *,
    node_type: str | None,
    step: StepStatus = "ok",
    status: str = "succeeded",
    created: str | None = None,
) -> str:
    rid = f"wfrun_{uuid4().hex[:10]}"
    row: dict[str, Any] = {"id": rid, "team_id": team, "workflow_id": wf, "version": 1, "digest": "d" * 64}
    await RunStore(tx).create(row | {"run_key": rid, "mode": "live", "input": {}, "created_by": "a"})
    await RunStore(tx).update(rid, status=status)
    if created:
        async with tx.tenant_tx() as c:
            await c.execute(sa.update(engine_runs).where(engine_runs.c.id == rid).values(created_at=created))
    if node_type:
        await SqlJournal(tx).begin(
            StepRow(rid, "review", 1, 1, step, "human", f"{rid}:review:1:1", node_type=node_type)
        )
    return rid


async def listed(tx: EngineTransactions, wf: str, team: str) -> dict[str, Any]:
    [row] = [d for d in await DefinitionStore(tx).summaries(CUTOFF, team=team) if d["workflow_id"] == wf]
    return row


async def publish(tx: EngineTransactions, wf: str, team: str) -> None:
    await DefinitionStore(tx).publish(
        wf, name="W", definition={}, digest="d" * 64, now="n", by="a", team=team, stage="live"
    )


async def test_the_list_counts_runs_that_opened_a_task_and_open_tasks(engine: AsyncEngine) -> None:
    tx, wf = EngineTransactions(engine), f"wf_{uuid4().hex[:8]}"
    with tenant_scope(f"t-{uuid4().hex[:6]}"):
        await publish(tx, wf, "team_cards")
        await run_with(tx, wf, "team_cards", node_type="ops.flow.humanReview", step="waiting", status="waiting")
        await run_with(tx, wf, "team_cards", node_type="ops.flow.humanReview", step="ok")  # decided: not open
        await run_with(tx, wf, "team_cards", node_type="ops.action.tool", step="ok")  # no Human Task
        await run_with(tx, wf, "team_cards", node_type=None)
        await run_with(tx, wf, "team_cards", node_type="ops.flow.humanReview", step="ok", created=OLD)  # outside 24h
        row = await listed(tx, wf, "team_cards")
        assert (row["recent"], row["reviewed"], row["open_reviews"]) == (4, 2, 1)


async def test_another_teams_runs_never_count(engine: AsyncEngine) -> None:
    tx, mine, theirs = EngineTransactions(engine), f"wf_{uuid4().hex[:8]}", f"wf_{uuid4().hex[:8]}"
    with tenant_scope(f"t-{uuid4().hex[:6]}"):
        await publish(tx, mine, "team_cards")
        await publish(tx, theirs, "team_lending")
        await run_with(tx, theirs, "team_lending", node_type="ops.flow.humanReview", step="waiting", status="waiting")
        seen = {d["workflow_id"]: d for d in await DefinitionStore(tx).summaries(CUTOFF, team="team_cards")}
        assert theirs not in seen
        assert (seen[mine]["reviewed"], seen[mine]["open_reviews"]) == (0, 0)
