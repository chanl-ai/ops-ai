"""The service's background processes as agents-service's Background page reads them: GET /health/background lists
each with its state."""

from __future__ import annotations

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
