"""GET /v1/tool-modules on the shared list contract: each view, count, facet and total agrees with the rows the list
shows, a page past the end answers the last page, and equal sort values keep one place across pages."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from .conftest import Api

VIEWS = ("needs_approval", "expiring", "expired", "failing", "security_review")


async def _list(api: Api, team: str | None = None, **params: Any) -> dict[str, Any]:
    r = await api.call("GET", "", team=team, params={"pageSize": 100, **params})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _in_view(r: dict[str, Any], view: str, now: datetime) -> bool:
    """What each view means, read off a row as the console shows it."""
    if view == "needs_approval":
        return r["approvalState"] in ("needs_approval", "draft")
    if view == "expired":
        return r["approvalState"] == "expired"
    if view == "security_review":
        return r["pendingReview"] is not None
    if view == "expiring":
        nxt = r.get("nextExpiry")
        return r["approvalState"] != "expired" and nxt is not None and datetime.fromisoformat(nxt) - now < timedelta(7)
    return r["errorRate"] >= 0.02 or not r["reachable"]


PINNED = {
    None: {"all": 15, "needs_approval": 4, "expiring": 2, "expired": 1, "failing": 1, "security_review": 1},
    # Its own modules, the workspace-level ones and Core Banking, approved for one of its workflows.
    "team_lending": {"all": 9, "needs_approval": 2, "expiring": 1, "expired": 0, "failing": 1, "security_review": 0},
}


@pytest.mark.parametrize("team", [None, "team_lending"])
async def test_views_counts_facets_and_stats_agree_with_the_rows(api: Api, team: str | None) -> None:
    every = await _list(api, team)
    rows, now = every["data"], datetime.now(UTC)
    assert every["viewCounts"] == PINNED[team]
    assert every["pagination"]["total"] == len(rows) == every["viewCounts"]["all"] == every["stats"]["modules"]
    for view in VIEWS:
        shown = await _list(api, team, view=view)
        want = sorted(r["id"] for r in rows if _in_view(r, view, now))
        assert sorted(r["id"] for r in shown["data"]) == want, view
        assert every["viewCounts"][view] == len(want), view
    facets = {
        "type": [r["type"] for r in rows],
        "access": [a for r in rows for a in r["accessClasses"]],
        "approvalState": [r["approvalState"] for r in rows],
    }
    for key, values in facets.items():
        assert every["facets"][key] == {v: values.count(v) for v in set(values)}, key
    stats = every["stats"]
    assert stats["operations"] == sum(r["operationCount"] for r in rows)
    assert stats["calls24h"] == sum(r["calls24h"] for r in rows)
    assert stats["expiringModules"] == every["viewCounts"]["expiring"]
    # A filter narrows the rows and leaves its own facet counting under the other filters only.
    writes = await _list(api, team, access="write")
    assert sorted(r["id"] for r in writes["data"]) == sorted(r["id"] for r in rows if "write" in r["accessClasses"])
    assert writes["facets"]["access"] == every["facets"]["access"]
    named = await _list(api, team, ids=rows[0]["id"], search="no module is called this")
    assert [r["id"] for r in named["data"]] == [rows[0]["id"]], "ids name rows whatever the search says"


async def test_pages_keep_one_order_and_a_page_past_the_end_answers_the_last(api: Api) -> None:
    every = await _list(api, sortBy="ownerTeam", sortOrder="asc")
    ids = [r["id"] for r in every["data"]]
    owners = [r["ownerTeam"] for r in every["data"]]
    assert len(set(owners)) < len(owners), "the seed needs modules sharing an owner, so ties are paged"
    paged: list[str] = []
    for page in range(1, len(ids) + 1):
        r = await api.call("GET", "", params={"pageSize": 1, "page": page, "sortBy": "ownerTeam", "sortOrder": "asc"})
        paged += [m["id"] for m in r.json()["data"]["data"]]
    assert paged == ids, "every row once, in one order"
    past = (await api.call("GET", "", params={"pageSize": 5, "page": 99})).json()["data"]
    total = past["pagination"]["total"]
    assert past["pagination"]["page"] == -(-total // 5)
    assert len(past["data"]) == total - 5 * (past["pagination"]["page"] - 1)
