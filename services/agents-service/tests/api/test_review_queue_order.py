"""Human Tasks grouped by case (c-460), by failure mode: the queue ordered or grouped in the browser instead of by the
route; the next task after a decision skipping the rest of its case; a place that orders differently from the list it
steps through, or builds every review to do it; and a case title shown to a person whose teams do not hold the case."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from ops_agents.api import engine_reviews, hitl_facade
from ops_agents.api.task_type_seeds import seeded_store
from ops_agents.store.cases import CaseStore
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import RunStore
from tests.api.test_case_page import data
from tests.api.test_case_routes import started_run
from tests.api.test_reviews_list_reads import old_waiting
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, TENANT


async def _case(s: Stack, subject: str, team: str = "team_ops") -> str:
    _, rt = s
    with tenant_scope(TENANT):
        opened = await CaseStore(rt.db).open(
            team_id=team,
            subject=subject,
            priority="high",
            by="james@harborpine.example",
            customer_id=f"C-{subject[-1]}",
            customer_name="Marcus Bell",
            assignee="james@harborpine.example",
            fields={},
        )
    return str(opened.case["id"])


async def _waiting_on(s: Stack, case_id: str, tag: str, due_in_hours: float) -> str:
    """A run on the case waiting on an acknowledgement task due `due_in_hours` from now; its review id."""
    c, rt = s
    run = await started_run(c, BUILDER, f"q460_{tag}")
    with tenant_scope(TENANT):
        await CaseStore(rt.db).add_event(case_id, "run", ref=run, detail={}, by="james@harborpine.example")
    opened = (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    payload = {
        "node": "review",
        "iteration": 1,
        "step_id": f"{run}:review:1",
        "title": f"Send the reply {tag}?",
        "taskType": {"id": "acknowledgement"},
        "params": {"title": f"Send the reply {tag}?", "reply": "We have your letter."},
        "openedAt": opened,
        "slaHours": 1 + due_in_hours,
    }
    waiting = {"node": "review", "iteration": 1, "interruptId": f"i_{tag}", "payload": payload}
    with tenant_scope(TENANT):
        await RunStore(EngineTransactions(rt.db)).update(run, status="waiting", waiting=waiting)
    return f"{run}:review:1"


async def _seed(s: Stack) -> dict[str, Any]:
    """Case A's tasks are due in 5 and 30 hours, case B's one in 10. By deadline alone B's would sit between A's two;
    grouped, A's two come first (its soonest is sooner), then B's, then the reviews on no case with no deadline."""
    _, rt = s
    with tenant_scope(TENANT):
        await seeded_store(rt.db, "team_ops")
    a, b = await _case(s, "Dispute A"), await _case(s, "Dispute B")
    # Made in an order that is neither newest first (a_late, b_only, a_soon) nor by deadline (a_soon, b_only, a_late).
    a_soon = await _waiting_on(s, a, "a_soon", 5)
    b_only = await _waiting_on(s, b, "b_only", 10)
    a_late = await _waiting_on(s, a, "a_late", 30)
    await old_waiting(s, "q460", 1)
    return {"a": a, "b": b, "order": [a_soon, a_late, b_only]}


async def _grouped(s: Stack, **extra: Any) -> list[dict[str, Any]]:
    c, _ = s
    params = {"view": "open", "pageSize": 100, "group": "case"} | extra
    return cast(list[dict[str, Any]], data(await c.get("/reviews", params=params, headers=BUILDER))["data"])


async def test_the_route_orders_by_case_soonest_first_with_each_case_titled(stack: Stack) -> None:  # noqa: F811
    seeded = await _seed(stack)
    rows = await _grouped(stack)
    ids = [r["id"] for r in rows]
    on_case = [i for i in ids if i in seeded["order"]]
    assert on_case == seeded["order"], ids
    # The reviews on no case and with no deadline come after every case.
    assert ids[: len(on_case)] == on_case, ids
    titles = {r["id"]: r.get("caseTitle") for r in rows}
    assert [titles[i] for i in seeded["order"]] == ["Dispute A", "Dispute A", "Dispute B"], titles
    assert all(titles[i] is None for i in ids if i not in seeded["order"]), titles


async def test_next_after_a_task_is_the_rest_of_its_case_then_the_next_case(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    seeded = await _seed(stack)
    ids = [r["id"] for r in await _grouped(stack)]
    for at, review_id in enumerate(ids):
        place = data(
            await c.get(f"/reviews/{review_id}/place", params={"view": "open", "group": "case"}, headers=BUILDER)
        )
        assert (place["position"], place["total"]) == (at + 1, len(ids)), (review_id, place)
        assert place["next"] == (ids[at + 1] if at + 1 < len(ids) else None), (review_id, place)
    # Pinned to the seeded order, so the test cannot pass on a queue that merely agrees with itself.
    a_soon, a_late, b_only = seeded["order"]
    for current, following in ((a_soon, a_late), (a_late, b_only)):
        place = data(
            await c.get(f"/reviews/{current}/place", params={"view": "open", "group": "case"}, headers=BUILDER)
        )
        assert place["next"] == following, (current, place)


async def test_a_grouped_place_builds_no_review(stack: Stack, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c, _ = stack
    seeded = await _seed(stack)

    async def built(*_: Any, **__: Any) -> dict[str, Any]:
        raise AssertionError("the place built a review")

    monkeypatch.setattr(engine_reviews, "view", built)
    monkeypatch.setattr(hitl_facade, "review_view", built)
    res = await c.get(f"/reviews/{seeded['order'][0]}/place", params={"view": "open", "group": "case"}, headers=BUILDER)
    assert res.status_code == 200, res.text


async def test_a_case_of_a_team_the_reader_is_not_in_has_no_title(stack: Stack) -> None:  # noqa: F811
    seeded = await _seed(stack)
    other = await _case(stack, "Fraud ring Z", team="team_fraud")
    # A run of the reader's team recorded on the other team's case: the review shows, the other team's subject does not.
    fraud_task = await _waiting_on(stack, other, "fraud", 1)
    rows = {r["id"]: r for r in await _grouped(stack)}
    assert fraud_task in rows, list(rows)
    assert rows[fraud_task].get("caseTitle") is None, rows[fraud_task]
    assert rows[seeded["order"][0]]["caseTitle"] == "Dispute A"
