"""The Overview's counts, through the real routes and worker, by failure mode: a case waiting on the customer
or resolved counted as needing a person; a paused case counted past its deadline; a case with a review open on its
run not counted as awaiting approval; the review counts disagreeing with Human Tasks."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx

from ops_engine.worker import Worker
from tests.engine.test_lifecycle import (
    JAMES,
    MAYA,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    data,
    definition,
    drain,
    engine,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    publish,
    save,
    stack,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    start,
)

PAST = "2020-01-01T00:00:00.000Z"


async def case(c: httpx.AsyncClient, subject: str, **patch: Any) -> str:
    made = data(await c.post("/v1/cases", json={"subject": subject}, headers=JAMES))
    if patch:
        data(await c.patch(f"/v1/cases/{made['id']}", json=patch, headers=JAMES))
    return str(made["id"])


async def test_the_overview_counts_what_waits_on_a_person(
    stack: tuple[httpx.AsyncClient, Worker],  # noqa: F811
) -> None:
    c, w = stack
    # Runs queued by earlier tests on this database settle first, so the counts move only by what this test does.
    await drain(w)
    before = data(await c.get("/v1/overview", headers=JAMES))
    wid = f"wf_{uuid4().hex[:8]}"
    await save(c, definition(wid))
    await publish(c, wid)
    run_id = data(await start(c, wid, 250))["runId"]
    await drain(w)
    on_review = await case(c, "Refund dispute")
    data(await c.post(f"/v1/cases/{on_review}/events", json={"kind": "run", "ref": run_id}, headers=JAMES))
    await case(c, "Overdue", resolutionDueAt=PAST)
    await case(c, "Waiting on the customer", status="waiting_on_customer", resolutionDueAt=PAST)
    await case(c, "Done", status="resolved", resolutionDueAt=PAST)

    after = data(await c.get("/v1/overview", headers=JAMES))
    reviews = data(await c.get("/reviews", params={"pageSize": 500}, headers=JAMES))
    assert (after["openReviews"], after["overdueReviews"]) == (
        reviews["viewCounts"]["open"],
        reviews["viewCounts"]["overdue"],
    )
    grew = {k: after["cases"][k] - before["cases"][k] for k in ("open", "breaching", "awaitingApproval")}
    assert grew == {"open": 2, "breaching": 1, "awaitingApproval": 1}, after["cases"]
    assert any(r["id"] == f"{run_id}:review:1" for r in after["urgentReviews"]) or after["openReviews"] > 5
