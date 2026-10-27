"""Human Tasks and cases (c-128), through the real routes and worker, by failure mode: a review of a run on a case
does not say which case; its decision is missing from the case's timeline."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx

from ops_engine.worker import Worker
from tests.engine.test_lifecycle import (  # noqa: F401
    JAMES,  # pyright: ignore[reportUnusedImport]
    MAYA,  # pyright: ignore[reportUnusedImport]
    data,  # pyright: ignore[reportUnusedImport]
    definition,  # pyright: ignore[reportUnusedImport]
    drain,  # pyright: ignore[reportUnusedImport]
    engine,  # pyright: ignore[reportUnusedImport]
    publish,  # pyright: ignore[reportUnusedImport]
    save,  # pyright: ignore[reportUnusedImport]
    stack,  # pyright: ignore[reportUnusedImport]
    start,  # pyright: ignore[reportUnusedImport]
)


async def test_a_review_names_its_case_and_its_decision_lands_on_the_timeline(
    stack: tuple[httpx.AsyncClient, Worker],  # noqa: F811
) -> None:
    c, w = stack
    wid = f"wf_{uuid4().hex[:8]}"
    await save(c, definition(wid))
    await publish(c, wid)
    run_id = data(await start(c, wid, 250))["runId"]
    await drain(w)
    case = data(await c.post("/v1/cases", json={"subject": "Refund dispute"}, headers=JAMES))
    added = await c.post(f"/v1/cases/{case['id']}/events", json={"kind": "run", "ref": run_id}, headers=JAMES)
    assert added.status_code == 201, added.text

    rows: list[dict[str, Any]] = data(await c.get("/reviews", params={"pageSize": 500}, headers=MAYA))["data"]
    [row] = [r for r in rows if r["id"] == f"{run_id}:review:1"]
    assert row["caseId"] == case["id"]
    data(
        await c.post(
            f"/reviews/{run_id}/decision", json={"decision": "approved", "reason": "Within policy"}, headers=MAYA
        )
    )
    timeline = data(await c.get(f"/v1/cases/{case['id']}", headers=JAMES))["events"]
    decision = [e for e in timeline if e["kind"] == "decision"]
    assert [(e["ref"], e["by"], e["detail"]["decision"]) for e in decision] == [
        (f"{run_id}:review:1", "m.okafor@harborpine.example", "approved")
    ]
