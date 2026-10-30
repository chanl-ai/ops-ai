"""The Workflows list for the current engine only (c-562): the console no longer shows workflows of the earlier engine,
so with `engine=current` a v1 workflow must not reach a page, its total or its status counts. Without it the list still
holds both, for the callers that have not moved."""

from __future__ import annotations

from httpx import AsyncClient

from ops_service_kit.ids import new_id

TEAM = {"X-Team-Id": "team_cards"}


def runner(wid: str) -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "id": wid,
        "name": f"Runner {wid}",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "parameters": {}},
        ],
        "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
    }


async def test_the_current_engine_list_leaves_out_every_earlier_workflow_with_its_counts(client: AsyncClient) -> None:
    old = await client.post("/v1/workflows", json={"name": f"Old {new_id('x')}", "trigger": "manual"}, headers=TEAM)
    assert old.status_code == 201, old.text
    wid = new_id("cur").replace("-", "_")
    saved = await client.post("/v1/workflows/definitions", json={"definition": runner(wid)}, headers=TEAM)
    assert saved.status_code == 201, saved.text

    both = (await client.get("/v1/workflows", params={"pageSize": 200}, headers=TEAM)).json()["data"]
    assert {"v1", "v2"} <= {w["engine"] for w in both["data"]}, "without the filter both kinds are listed"

    res = await client.get("/v1/workflows", params={"engine": "current", "pageSize": 200}, headers=TEAM)
    assert res.status_code == 200, res.text
    current = res.json()["data"]
    assert {w["engine"] for w in current["data"]} == {"v2"} and wid in {w["id"] for w in current["data"]}
    assert current["pagination"]["total"] == len(current["data"]), "the total counts current workflows only"
    assert sum(current["facets"]["status"].values()) == len(current["data"]), "so do the status counts"
