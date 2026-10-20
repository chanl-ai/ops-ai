"""A task that shows cases lists the ones its run and its child runs opened (round 3 design check), on PostgreSQL with
the real worker, by failure mode: the reply check shows no cases though the run's child runs opened them; a step has to
pass them for them to show."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api import engine_reviews
from ops_agents.store.cases import CaseStore
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store.tables import engine_steps
from tests.engine.review_flows import flow, paused


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def _task(rt: Any, tenant: str, run_id: str) -> dict[str, Any] | None:
    with tenant_scope(tenant):
        return (await engine_reviews.get(rt, run_id)).get("task")


async def test_a_reply_check_lists_the_cases_its_run_and_child_runs_opened(engine: AsyncEngine) -> None:
    """Round 3 design check: the acknowledgement showed no cases, though its run's child runs opened them. A type that
    declares `cases` gets them from the run, each linked, with no step having to pass them."""
    ack = flow({"title": "Send it?", "taskType": {"id": "acknowledgement"}, "params": {"reply": "We have it."}})
    tenant, run_id, rt, _ = await paused(engine, ack)
    child = f"wfrun_{uuid4().hex[:10]}"
    with tenant_scope(tenant):
        cases = CaseStore(engine)
        mine = (await cases.open(team_id="team_a", subject="Levy for Marcus Bell", priority="normal", by="a@x")).case[
            "id"
        ]
        other = (await cases.open(team_id="team_a", subject="Levy for Ann Lee", priority="normal", by="a@x")).case["id"]
        await cases.add_event(mine, "run", ref=run_id, detail={}, by="a@x")
        await cases.add_event(other, "run", ref=child, detail={}, by="a@x")
        async with engine.begin() as c:
            await c.execute(
                engine_steps.update()
                .where(engine_steps.c.run_id == run_id, engine_steps.c.node_id == "start")
                .values(output={"runs": [{"runId": child, "index": 0}]})
            )
    task = await _task(rt, tenant, run_id)
    regions = {r["region"]: r["data"] for r in (task or {}).get("regions", [])}
    assert [c["subject"] for c in regions["cases"]["cases"]] == ["Levy for Marcus Bell", "Levy for Ann Lee"], regions
