"""The Overview's lists and counts (c-552), through the real routes and worker, by failure mode: a Human Task assigned
to someone else listed as waiting for me; the lists out of order (tasks oldest first, runs newest first, cases soonest
deadline first); a resolved, paused or later case listed as due; a count that disagrees with Human Tasks. Team
isolation is tests/api/test_overview_team.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx

from ops_engine.worker import Worker
from tests.engine.test_lifecycle import (
    JAMES,
    MAYA,
    data,
    definition,
    drain,
    engine,  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture
    publish,
    save,
    stack,  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture
    start,
)

PAST = "2020-01-01T00:00:00.000Z"
# Earlier than any deadline another test sets, so this case is first among the cases due.
EARLIEST = "1999-01-01T00:00:00.000Z"
# A person no earlier test assigned anything to, so the oldest five waiting for them are this test's.
FRESH = {"X-Dev-User": f"p{uuid4().hex[:8]}@harborpine.example"}


def soon(**delta: float) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def case(c: httpx.AsyncClient, subject: str, **patch: Any) -> str:
    made = data(await c.post("/v1/cases", json={"subject": subject}, headers=JAMES))
    if patch:
        data(await c.patch(f"/v1/cases/{made['id']}", json=patch, headers=JAMES))
    return str(made["id"])


async def test_the_overview_lists_what_waits_on_the_person_in_order(
    stack: tuple[httpx.AsyncClient, Worker],  # noqa: F811
) -> None:
    c, w = stack
    await drain(w)
    wid = f"wf_{uuid4().hex[:8]}"
    await save(c, definition(wid))
    await publish(c, wid)
    first = data(await start(c, wid, 250))["runId"]
    await drain(w)
    second = data(await start(c, wid, 300))["runId"]
    await drain(w)
    reviews = [f"{first}:review:1", f"{second}:review:1"]
    assigned = data(
        await c.post("/reviews/assign", json={"ids": reviews, "assignee": FRESH["X-Dev-User"]}, headers=MAYA)
    )
    assert assigned["updated"] == reviews, assigned

    before = data(await c.get("/v1/overview", headers=JAMES))["counts"]["casesDue"]
    overdue = await case(c, f"Overdue {wid}", resolutionDueAt=EARLIEST)
    await case(c, f"Due shortly {wid}", resolutionDueAt=soon(minutes=1))
    await case(c, f"Later {wid}", resolutionDueAt=soon(days=3))
    await case(c, f"Resolved {wid}", status="resolved", resolutionDueAt=PAST)
    await case(c, f"Waiting on the customer {wid}", status="waiting_on_customer", resolutionDueAt=PAST)

    fresh = data(await c.get("/v1/overview", headers=FRESH))
    mine = [r["id"] for r in fresh["waitingForMe"] if r["id"] in reviews]
    assert mine == reviews, fresh["waitingForMe"]
    row = next(r for r in fresh["waitingForMe"] if r["id"] == reviews[0])
    assert row["title"] and row["createdAt"], row

    james = data(await c.get("/v1/overview", headers=JAMES))
    assert not {r["id"] for r in james["waitingForMe"]} & set(reviews), "listed for James though assigned to another"
    listed = data(await c.get("/reviews", params={"view": "mine", "pageSize": 500}, headers=FRESH))
    assert fresh["counts"]["waitingForMe"] == listed["viewCounts"]["mine"], (fresh["counts"], listed["viewCounts"])

    runs = [r["id"] for r in fresh["runsInFlight"] if r["id"] in (first, second)]
    assert runs == [second, first], fresh["runsInFlight"]
    assert all(r["state"] in ("running", "waiting") for r in fresh["runsInFlight"]), fresh["runsInFlight"]

    # Due today or past, and still the team's: the overdue and the shortly-due case; not later, resolved or paused.
    grew = data(await c.get("/v1/overview", headers=JAMES))["counts"]["casesDue"] - before
    assert grew == 2, grew
    due = fresh["casesDue"]
    assert overdue in [r["id"] for r in due], due
    assert [r["resolutionDueAt"] for r in due] == sorted(r["resolutionDueAt"] for r in due), due
    assert fresh["counts"]["runsInFlight"] >= 2, fresh["counts"]
