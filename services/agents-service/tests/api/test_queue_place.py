"""A task's place in its queue (GET /reviews/{id}/place), by failure mode: the place is read by building every review
in the tenant in full (each task's type, assist, policies and wording), which made it 2.3 to 2.8 s on the shared stack
for three numbers; and a cheaper read that orders the queue differently from the list, so "5 of 24" and Next disagree
with what Human Tasks shows."""

from __future__ import annotations

from typing import Any, cast

import pytest

from ops_agents.api import engine_reviews, hitl_facade
from ops_agents.api.task_type_seeds import seeded_store
from ops_agents.store.tenancy import tenant_scope
from tests.api.test_case_page import data, typed_case
from tests.api.test_reviews_list_reads import old_waiting, typed_waiting
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import ADMIN, BUILDER, TENANT


async def _queue(s: Stack) -> list[dict[str, Any]]:
    c, rt = s
    with tenant_scope(TENANT):
        await seeded_store(rt.db)
    await typed_waiting(s, await typed_case(s, customer="C-place"), 2)
    await old_waiting(s, "place", 2)
    return cast(
        list[dict[str, Any]],
        data(await c.get("/reviews", params={"view": "all", "pageSize": 100}, headers=BUILDER))["data"],
    )


async def test_a_place_builds_no_review(stack: Stack, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, _ = stack
    listed = await _queue(stack)

    async def built(*_: Any, **__: Any) -> dict[str, Any]:
        raise AssertionError("the place built a review")

    monkeypatch.setattr(engine_reviews, "view", built)
    monkeypatch.setattr(hitl_facade, "review_view", built)
    first = next(r for r in listed if r["status"] == "pending")
    res = await c.get(f"/reviews/{first['id']}/place", headers=BUILDER)
    assert res.status_code == 200, res.text


@pytest.mark.parametrize("view", ["open", "resolved", "all"])
async def test_a_place_follows_the_lists_order(stack: Stack, view: str) -> None:  # noqa: F811
    c, _ = stack
    await _queue(stack)
    # Decide one, so the resolved view has a decided engine review.
    listed = data(await c.get("/reviews", params={"view": "open", "pageSize": 100}, headers=BUILDER))["data"]
    old = next(r for r in listed if str(r.get("workflowId", "")).startswith("old"))
    decided = await c.post(
        f"/reviews/{old['id']}/decision", json={"decision": "rejected", "reason": "No"}, headers=ADMIN
    )
    assert decided.status_code == 200, decided.text
    ids = [
        r["id"] for r in data(await c.get("/reviews", params={"view": view, "pageSize": 100}, headers=BUILDER))["data"]
    ]
    assert ids, view
    for at, review_id in enumerate(ids):
        place = data(await c.get(f"/reviews/{review_id}/place", params={"view": view}, headers=BUILDER))
        assert (place["position"], place["total"]) == (at + 1, len(ids)), (view, review_id, place)
        assert place["previous"] == (ids[at - 1] if at else None) and place["next"] == (
            ids[at + 1] if at + 1 < len(ids) else None
        )
