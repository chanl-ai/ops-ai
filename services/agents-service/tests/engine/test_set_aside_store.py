"""A set-aside email's kept copy on PostgreSQL (c-561), by failure mode: the runtime role may only add trigger events,
so dropping the copy once its run starts, or after 30 days, is refused and the poll that tries it fails; and the copy
is listed with the trigger events."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.tenancy import tenant_scope
from ops_agents.store.trigger_events import TriggerEvent, TriggerEvents


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def test_the_kept_copy_is_dropped_once_run_or_old_and_never_listed(engine: AsyncEngine) -> None:
    tenant, events = f"t-{uuid4().hex[:8]}", TriggerEvents(engine)

    async def aside(key: str) -> str:
        await events.add(
            TriggerEvent(
                team_id="team_ops",
                workflow_id="levy_intake",
                source="email:levy@bank.example",
                event_key=key,
                sender="registry@court.example",
                subject=key,
                received_at="2026-10-29T09:00:00Z",
                outcome="set_aside",
                item='{"key": "kept"}',
            )
        )
        rows, _ = await events.page("levy_intake", team_id="team_ops", page=1, page_size=10)
        return str(next(r for r in rows if r["event_key"] == key)["id"])

    with tenant_scope(tenant):
        ran, old = await aside("email:ran"), await aside("email:old")
        rows, _ = await events.page("levy_intake", team_id="team_ops", page=1, page_size=10)
        assert all("item" not in r for r in rows), "the trigger list never carries the mail"
        assert ((await events.set_aside(ran)) or {}).get("item") == '{"key": "kept"}'
        await events.forget(ran)
        await events.forget_before("levy_intake", "2999-01-01")
        assert await events.set_aside(ran) is None and await events.set_aside(old) is None
