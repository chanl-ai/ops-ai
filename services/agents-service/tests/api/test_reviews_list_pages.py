"""The reviews list builds the full review only for the rows its page shows (c-451). The console's open count asks for
one row and read every waiting task in full, about 2.6 s on staging; counts, facets and stats now come from rows that
read no task, wording or reply. By failure mode: a page of one builds every review; a small page counts, facets or
orders differently from a large one, or carries the row's build key onto the wire; a search misses a task whose
title comes from its task type."""

from __future__ import annotations

from typing import Any, cast

import pytest

from ops_agents.api import engine_reviews
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import RUN_PREFIX, RunStore
from tests.api.test_case_page import data, typed_case
from tests.api.test_case_routes import started_run
from tests.api.test_reviews_list_reads import typed_waiting
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, TENANT

WAITING = 4


def _list(rows: Any) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], rows)


async def test_a_page_of_one_builds_one_review(stack: Stack, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, _ = stack
    await typed_waiting(stack, await typed_case(stack, customer="C-page"), WAITING)
    built: list[str] = []
    real = engine_reviews.view

    async def counted(*a: Any, **k: Any) -> dict[str, Any]:
        built.append(str(a[1]["id"]))
        return await real(*a, **k)

    monkeypatch.setattr(engine_reviews, "view", counted)
    body = data(await c.get("/reviews", params={"view": "open", "page": 1, "pageSize": 1}, headers=BUILDER))
    assert body["viewCounts"]["open"] >= WAITING
    assert len(body["data"]) == 1 and len(built) == 1, built


async def test_a_page_of_one_counts_facets_and_orders_as_a_page_of_all(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await typed_waiting(stack, await typed_case(stack, customer="C-same"), WAITING)
    for view in ("open", "all"):
        one = data(await c.get("/reviews", params={"view": view, "page": 1, "pageSize": 1}, headers=BUILDER))
        every = data(await c.get("/reviews", params={"view": view, "page": 1, "pageSize": 200}, headers=BUILDER))
        assert (one["viewCounts"], one["facets"], one["stats"]) == (
            every["viewCounts"],
            every["facets"],
            every["stats"],
        )
        assert one["pagination"]["total"] == every["pagination"]["total"] == len(_list(every["data"]))
        assert _list(one["data"])[0] == _list(every["data"])[0]
        assert not any(engine_reviews.BUILD in r for r in _list(every["data"]))
        steps = [r for r in _list(every["data"]) if str(r["id"]).startswith(RUN_PREFIX)]
        assert len(steps) >= WAITING and all("task" in r for r in steps), [r["id"] for r in steps]


async def test_a_search_finds_a_task_by_the_title_its_task_type_gives_it(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    run = await started_run(c, BUILDER, "search_title")
    payload = {
        "node": "review",
        "iteration": 1,
        "step_id": f"{run}:review:1",
        "title": "Send the reply?",
        "taskType": {"id": "acknowledgement"},
        "params": {"title": "Letter for Zebedee", "reply": "We have your letter."},
    }
    waiting = {"node": "review", "iteration": 1, "interruptId": "s1", "payload": payload}
    with tenant_scope(TENANT):
        await RunStore(EngineTransactions(rt.db)).update(run, status="waiting", waiting=waiting)
    found = data(await c.get("/reviews", params={"view": "open", "search": "zebedee"}, headers=BUILDER))
    assert [r["title"] for r in _list(found["data"])] == ["Letter for Zebedee"]
