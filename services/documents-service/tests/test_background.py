"""The service's background processes as agents-service's Background page reads them: GET /health/background lists
each with its state, and a pass that fails shows there."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_documents.store import documents_relay
from ops_store.outbox import run_relay
from ops_store.testing import loop_reports_failure

from .conftest import Make


async def test_health_background_lists_each_process_with_its_state(make: Make) -> None:
    s = make()
    async with s.client as c:
        answer = await c.get("/health/background")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert set(body) == {"processes"}, body
    rows = {p["key"]: p for p in body["processes"]}
    assert set(rows) == {"documents_relay", "document_reading"}, rows
    assert set(rows["documents_relay"]) == {
        "key", "service", "title", "does", "everySeconds", "state", "instances", "lastRunAt", "nextRunAt",
        "doneHour", "waiting", "lastError", "lastErrorAt",
    }, rows  # fmt: skip


async def test_the_relay_reports_a_failed_pass_on_health(make: Make, engine: AsyncEngine) -> None:
    class Agents:
        async def post(self, path: str, body: Any, /, *, tenant: str, team: str) -> None: ...

    outbox = documents_relay(engine, {"agents": Agents()})
    stop = asyncio.Event()
    s = make(background=[lambda: run_relay(outbox, key="documents_relay", stop=stop)])
    # The database goes away: the next pass cannot read the outbox at all.
    gone = create_async_engine("sqlite+aiosqlite://")
    try:
        async with s.client as c, s.app.router.lifespan_context(s.app):
            await loop_reports_failure(c, "documents_relay", lambda: setattr(outbox, "engine", gone))
    finally:
        stop.set()
        await gone.dispose()
