"""A service event runs its handler workflow to the end on PostgreSQL (c-258), under the tenant role and a real worker:
the handler is published to the tenant on its first event and runs to its outcome; a repeat after it finished
returns the same run; another tenant's event of the same name and key is its own. Runs on the migrated test database."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api.service_events import emit
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import RunStore
from tests.api.test_service_events import event_workflow
from tests.engine.test_worker import CountingTools, drain, worker


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def deleted(rt: Any, tenant: str, key: str) -> dict[str, Any]:
    with tenant_scope(tenant):
        return await emit(
            rt, name="file.deleted", key=key, team_id="team_ops", source="files", actor=None, payload={"fileId": key}
        )


async def test_an_event_runs_its_handler_to_the_end_once_per_tenant(engine: AsyncEngine) -> None:
    rt: Any = SimpleNamespace(db=engine, event_workflows=[event_workflow()], event_workflows_seen=set())
    ours, theirs = f"t-{uuid4().hex[:8]}", f"t-{uuid4().hex[:8]}"
    first = await deleted(rt, ours, "fil_9")
    [run_id] = first["run_ids"]
    await drain(worker(engine, CountingTools(), InMemorySaver()))
    with tenant_scope(ours):
        run = await RunStore(EngineTransactions(engine)).get(run_id) or {}
    assert (run["status"], run["outcome"], run["output"]) == ("succeeded", "purged", "fil_9"), run
    again = await deleted(rt, ours, "fil_9")
    assert again["run_ids"] == [run_id] and again["attempts"] == 1, again
    other = await deleted(rt, theirs, "fil_9")
    assert other["run_ids"] and other["run_ids"] != [run_id], "another tenant's event starts its own run"
