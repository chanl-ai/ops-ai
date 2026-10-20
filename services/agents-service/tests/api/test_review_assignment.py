"""Assigning Human Tasks (c-074), by failure mode: Assign to me doing nothing (every id skipped), an assigned review
missing from Assigned to me, a reassignment losing who had it before, someone who may not decide a review taking it,
and a decided review being assigned."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from httpx import AsyncClient

from ops_agents.api.deps import Runtime
from ops_agents.store.review_assignments import review_assignments

from .test_hitl_facade import data, paused_dispute, stack  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture

# The workflow's own identity: it requested the review, so it may not decide or take it.
REQUESTER = {"X-Dev-User": "workflow:complex_workflow"}


async def assign(client: AsyncClient, ids: list[str], assignee: str | None = None, **headers: str) -> dict[str, Any]:
    r = await client.post(
        "/reviews/assign", json={"ids": ids, **({"assignee": assignee} if assignee else {})}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_assign_to_me_puts_the_review_in_assigned_to_me(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    client, _ = stack
    tid = await paused_dispute(client)
    assert (await data(client, "/reviews?view=mine&page=1&pageSize=25"))["viewCounts"]["mine"] == 0
    assert await assign(client, [tid]) == {"updated": [tid], "skipped": []}
    mine = await data(client, "/reviews?view=mine&page=1&pageSize=25")
    assert [r["id"] for r in mine["data"]] == [tid] and mine["viewCounts"]["mine"] == 1
    assert mine["stats"]["unassigned"] == 0
    review = await data(client, f"/reviews/{tid}")
    assert review["assignee"] and review["assignee"] == mine["data"][0]["assignee"]


async def test_a_reassignment_keeps_who_had_it_before(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    client, rt = stack
    tid = await paused_dispute(client)
    await assign(client, [tid])
    assert await assign(client, [tid], "m.okafor@northfieldbank.com") == {"updated": [tid], "skipped": []}
    assert (await data(client, f"/reviews/{tid}"))["assignee"] == "m.okafor@northfieldbank.com"
    assert (await data(client, "/reviews?view=mine&page=1&pageSize=25"))["viewCounts"]["mine"] == 0
    async with rt.db.connect() as c:
        rows = (
            await c.execute(sa.select(review_assignments.c.assignee).order_by(review_assignments.c.assigned_at))
        ).all()
    assert len(rows) == 2 and rows[-1].assignee == "m.okafor@northfieldbank.com"


async def test_only_someone_who_may_decide_assigns_and_a_decided_review_is_not_assigned(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    client, _ = stack
    tid = await paused_dispute(client)
    refused = await assign(client, [tid], **REQUESTER)
    assert refused["updated"] == [] and "may decide" in refused["skipped"][0]["reason"], refused
    decided = await client.post(f"/reviews/{tid}/decision", json={"decision": "rejected", "reason": "Not a dispute."})
    assert decided.status_code == 200, decided.text
    late = await assign(client, [tid])
    assert late["updated"] == [] and "already decided" in late["skipped"][0]["reason"], late
    assert (await assign(client, ["no_such_review"]))["skipped"][0]["id"] == "no_such_review"
