"""Who gets a secret use row, by failure mode: a person's read (a Test connection, a tool call) leaves no row; a mail
listener that reads its mailbox's secret every few seconds leaves no row at all, so an automated use is invisible, or
one row per poll, which floods the audit; one listener's row stands in for another's, or yesterday's for today's."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.store.secrets import SecretStore

TEAM, SECRET = "team_platform", "MAILBOX_PASSWORD"
# Noon, so a few seconds later is the same day.
NOON = datetime(2026, 11, 16, 12, tzinfo=UTC)


async def _uses(store: SecretStore, tenant: str) -> list[tuple[str, str | None]]:
    return [(r.actor, r.tool) for r in await store.audit(tenant, TEAM) if r.action == "used"]


async def test_a_persons_read_is_audited_each_time(engine: AsyncEngine, tenant: str) -> None:
    store, now = SecretStore(engine), NOON
    await store.create(tenant, TEAM, SECRET, f"ref-{uuid4().hex}", actor="sam", at=now)
    for _ in range(2):
        await store.use(tenant, TEAM, [SECRET], actor="sam", tool="mailbox:a@bank.example", at=now)
    assert await _uses(store, tenant) == [("sam", "mailbox:a@bank.example")] * 2


async def test_a_listener_leaves_one_row_a_day_for_each_mailbox_and_caller(engine: AsyncEngine, tenant: str) -> None:
    store, now = SecretStore(engine), NOON
    await store.create(tenant, TEAM, SECRET, f"ref-{uuid4().hex}", actor="sam", at=now)
    a, b, listener = "mailbox:a@bank.example", "mailbox:b@bank.example", "service:agents"
    for at in (now, now + timedelta(seconds=5), now + timedelta(seconds=10)):
        await store.use(tenant, TEAM, [SECRET], actor=listener, tool=a, at=at, audit=False)
    await store.use(tenant, TEAM, [SECRET], actor=listener, tool=b, at=now, audit=False)
    assert await _uses(store, tenant) == [(listener, a), (listener, b)], "one row per mailbox for the day"
    await store.use(tenant, TEAM, [SECRET], actor=listener, tool=a, at=now + timedelta(days=1), audit=False)
    assert await _uses(store, tenant) == [(listener, a), (listener, b), (listener, a)], "a new day gets its own row"
