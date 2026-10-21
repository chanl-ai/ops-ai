"""The case store (c-128), by failure mode: a producer's retry opening a second case, another team's case read, a
deadline counting while the case waits on the customer or never restarting, a field change with no timeline entry,
and a link recorded twice."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.store.base import metadata
from ops_agents.store.cases import CaseNotFound, CaseStore
from ops_agents.store.tenancy import tenant_scope

T0 = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
ANA = "ana@harborpine.example"


@pytest.fixture
async def store() -> AsyncIterator[CaseStore]:
    engine: AsyncEngine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    with tenant_scope("ten_a"):
        yield CaseStore(engine)
    await engine.dispose()


async def test_a_producers_retry_finds_the_case_it_opened(store: CaseStore) -> None:
    first = await store.open(
        team_id="team_ops", subject="Dispute W-88213", priority="high", by=ANA, producer_key="run:1"
    )
    again = await store.open(
        team_id="team_ops", subject="Dispute W-88213", priority="high", by=ANA, producer_key="run:1"
    )
    assert first.created and not again.created and again.case["id"] == first.case["id"]
    other = await store.open(team_id="team_fraud", subject="x", priority="low", by=ANA, producer_key="run:1")
    assert other.created, "the key is per team"


async def test_another_teams_case_is_not_found_or_listed(store: CaseStore) -> None:
    case = (await store.open(team_id="team_fraud", subject="x", priority="low", by=ANA)).case
    with pytest.raises(CaseNotFound):
        await store.get(case["id"], ["team_ops"])
    assert (await store.list(["team_ops"]))[1] == 0
    assert (await store.list(["team_fraud"]))[1] == 1


async def test_waiting_on_the_customer_pauses_both_deadlines_and_any_other_status_resumes_them(
    store: CaseStore,
) -> None:
    case = (await store.open(team_id="team_ops", subject="x", priority="normal", by=ANA, now=T0)).case
    response, resolution = case["response_due_at"], case["resolution_due_at"]
    await store.change(case["id"], {"status": "waiting_on_customer"}, by=ANA, now=T0 + timedelta(hours=1))
    overdue = await store.list(["team_ops"], overdue=True, now=T0 + timedelta(days=10))
    assert overdue[1] == 0, "a paused case is not overdue"
    after = await store.change(case["id"], {"status": "open"}, by=ANA, now=T0 + timedelta(hours=3))

    def moved(s: str) -> datetime:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    assert moved(after["response_due_at"]) - moved(response) == timedelta(hours=2)
    assert moved(after["resolution_due_at"]) - moved(resolution) == timedelta(hours=2)
    assert after["paused_since"] is None


async def test_each_field_change_is_on_the_timeline_and_a_link_is_recorded_once(store: CaseStore) -> None:
    a = (await store.open(team_id="team_ops", subject="a", priority="low", by=ANA)).case
    b = (await store.open(team_id="team_ops", subject="b", priority="low", by=ANA)).case
    await store.change(a["id"], {"assignee": "sam@harborpine.example", "priority": "urgent"}, by=ANA)
    await store.change(a["id"], {"priority": "urgent"}, by=ANA)
    await store.link(a["id"], b["id"], by=ANA)
    await store.link(b["id"], a["id"], by=ANA)
    kinds = [(e["kind"], e["detail"].get("field")) for e in await store.events(a["id"])]
    assert kinds == [("opened", None), ("field", "assignee"), ("field", "priority"), ("link", None)]
    assert [e["kind"] for e in await store.events(b["id"])] == ["opened", "link"]
