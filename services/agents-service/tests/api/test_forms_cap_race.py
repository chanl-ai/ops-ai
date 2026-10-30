"""A hosted form's daily cap under concurrent submissions (c-535), on PostgreSQL: two submissions at the last place
under the cap must not both pass. The email trigger's cap is safe only because one poller holds a lease; a form's
submissions arrive at once, so the form's row is locked while the day's starts are counted and the new one recorded."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.form_links import FormLinks, form_links
from ops_agents.store.tenancy import tenant_scope, tenant_tx
from ops_agents.store.trigger_events import TriggerEvent, trigger_events


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


def submission(form_id: str, n: int) -> TriggerEvent:
    return TriggerEvent(
        team_id="team_ops",
        workflow_id="payment_plan",
        source=f"form:{form_id}",
        event_key=f"form:{form_id}:{n}",
        sender="203.0.113.7",
        subject="Ask for a payment plan",
        received_at="",
        outcome="started",
    )


async def test_a_submission_waits_for_the_form_while_another_holds_it_then_sees_its_start(engine: AsyncEngine) -> None:
    """Concurrent submissions do not reliably overlap in a test, so the lock is held by hand: while another
    transaction holds the form's row, a submission must wait; once that one has recorded the day's last start and
    committed, the waiting one must see it and be refused."""
    tenant = f"t-{uuid4().hex[:8]}"
    links = FormLinks(engine)
    with tenant_scope(tenant):
        form = await links.create(
            team_id="team_ops",
            workflow_id="payment_plan",
            slug=f"pp-{uuid4().hex[:6]}",
            mode="link",
            daily_cap=1,
            expires_at=(datetime.now(UTC) + timedelta(days=30)).isoformat(),
            created_by="james@harborpine.example",
        )
        since = datetime.now(UTC).date().isoformat()
        async with tenant_tx(engine) as held:
            f = form_links
            await held.execute(sa.select(f.c.id).where(f.c.id == form["id"]).with_for_update())
            waiting = asyncio.create_task(
                links.reserve(form["id"], cap=1, since=since, event=submission(form["id"], 1))
            )
            await asyncio.sleep(0.5)
            assert not waiting.done(), "a submission went ahead while another held the form"
            first = submission(form["id"], 0)
            await held.execute(
                trigger_events.insert().values(
                    id=f"tev_{uuid4().hex[:12]}", team_id=first.team_id, workflow_id=first.workflow_id,
                    source=first.source, event_key=first.event_key, sender=first.sender, subject=first.subject,
                    received_at="", outcome="started", detail="{}", recorded_at=datetime.now(UTC).isoformat(),
                )
            )  # fmt: skip
        assert await waiting is None, "the waiting submission saw the start the other one recorded"
