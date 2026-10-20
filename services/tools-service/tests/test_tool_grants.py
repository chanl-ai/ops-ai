"""GET /v1/tool-modules/grants (c-144): every workflow's access to the modules the team sees, by view, with counts,
searched and paged on the server. One test per way the Access tab could show the wrong access."""

from __future__ import annotations

from typing import Any

import pytest

from .test_apply_tool_access import apply_access
from .test_calls import MODULE, Gateway, gateway  # noqa: F401  # pyright: ignore[reportUnusedImport]

BASE = f"/v1/tool-modules/{MODULE}"
SECURITY = {"X-Dev-User": "Nadia Petrov"}


@pytest.fixture
async def g(gateway: Gateway) -> Gateway:  # noqa: F811
    return gateway


async def _ask(g: Gateway, workflow: str, days: int) -> str:
    body = {
        "workflowId": workflow,
        "environment": "production",
        "operations": [g.tool("get_account")],
        "expiresInDays": days,
        "justification": "c-144 grants",
    }
    r = await g.client.post(f"{BASE}/approvals", json=body)
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


async def _grants(g: Gateway, **params: Any) -> dict[str, Any]:
    r = await g.client.get("/v1/tool-modules/grants", params=params)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_a_granted_and_an_asked_access_are_listed_and_one_ending_this_week_is_expiring(g: Gateway) -> None:
    before = (await _grants(g))["facets"]["view"]
    soon = await _ask(g, "wf_dispute", 3)
    # Decided in Human Tasks (c-166), applied here by agents-service.
    decided = await apply_access(g.client, g.tenant, {"id": soon, "moduleId": MODULE})
    assert decided.status_code == 200, decided.text
    asked = await _ask(g, "wf_dispute", 90)
    listed = await _grants(g, pageSize=100)
    by_id = {x["id"]: x for x in listed["data"]}
    assert by_id[soon]["status"] == "approved" and by_id[asked]["status"] == "requested"
    assert by_id[soon]["moduleId"] == MODULE and by_id[soon]["moduleName"], "each row names its module"
    after = listed["facets"]["view"]
    added = {v: after[v] - before.get(v, 0) for v in ("active", "expiring", "requested", "all")}
    assert added == {"active": 1, "expiring": 1, "requested": 1, "all": 2}, added
    assert soon in [x["id"] for x in (await _grants(g, view="expiring", pageSize=100))["data"]]
    requested = [x["id"] for x in (await _grants(g, view="requested", pageSize=100))["data"]]
    assert asked in requested and soon not in requested


async def test_the_list_is_searched_and_paged_on_the_server(g: Gateway) -> None:
    everything = await _grants(g, pageSize=100)
    assert everything["pagination"]["total"] >= 2, "the seed holds approvals to page through"
    first = await _grants(g, pageSize=1)
    assert len(first["data"]) == 1 and first["pagination"]["hasNext"] is True
    name = everything["data"][0]["workflowName"]
    found = (await _grants(g, search=name, pageSize=100))["data"]
    assert found and all(x["workflowName"] == name or name.lower() in str(x).lower() for x in found)
    assert (await _grants(g, search="no such workflow anywhere"))["data"] == []
