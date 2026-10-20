"""v2 definitions: YAML in, JSON stored, one version per digest, and per-node checks from the type registry. A v2
definition must never reach graph_versions, whose every reader parses v1."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from httpx import AsyncClient

BASIC = Path(__file__).parents[1] / "fixtures" / "engine" / "basic.yaml"


def basic() -> dict[str, Any]:
    return yaml.safe_load(BASIC.read_text())


async def test_yaml_is_stored_as_json_once_per_digest(client: AsyncClient) -> None:
    first = await client.post("/v1/workflows/definitions", json={"yaml": BASIC.read_text()})
    assert first.status_code == 201, first.text
    assert first.json()["data"]["version"] == 1
    again = await client.post("/v1/workflows/definitions", json={"definition": basic()})
    assert again.status_code == 200 and again.json()["data"]["version"] == 1, again.text
    changed = basic() | {"name": "Refund check, renamed"}
    second = await client.post("/v1/workflows/definitions", json={"definition": changed})
    assert second.json()["data"]["version"] == 2
    got = (await client.get("/v1/workflows/definitions/refund_check?version=1")).json()["data"]
    assert got["definition"]["nodes"][0]["typeVersion"] == 1
    assert [v["version"] for v in got["versions"]] == [1, 2]
    # Beside v1, not in it: the v1 graph list does not see it.
    graphs = (await client.get("/v1/graphs")).json()["data"]
    assert "refund_check" not in {g["name"] for g in graphs}


async def test_each_broken_node_gets_its_own_check(client: AsyncClient) -> None:
    d = basic()
    d["nodes"].append({"id": "ghost", "type": "ops.flow.teleport", "typeVersion": 1})
    d["nodes"].append({"id": "old", "type": "ops.data.set", "typeVersion": 9})
    d["nodes"].append({"id": "orphan", "type": "ops.flow.end", "typeVersion": 1})
    d["connections"] = [c for c in d["connections"] if c["from"] != {"node": "review", "port": "reject"}]
    d["connections"].append({"from": {"node": "big", "port": "maybe"}, "to": {"node": "small", "port": "in"}})
    res = await client.post("/v1/workflows/definitions/validate", json={"definition": d})
    body = res.json()["data"]
    assert body["ok"] is False
    found = {(c["node"], c["code"]) for c in body["checks"]}
    assert ("ghost", "unknown_type") in found
    assert ("old", "unknown_type_version") in found
    assert ("big", "unknown_port") in found
    assert ("review", "unconnected_port") in found
    assert ("orphan", "unreachable") in found
    # End nodes have no out port, so none of the four ends is reported as leading nowhere.
    assert not [c for c in body["checks"] if c["code"] == "unconnected_port" and c["node"] != "review"]
    refused = await client.post("/v1/workflows/definitions", json={"definition": d})
    assert refused.status_code == 422
    assert refused.json()["error"]["details"]["checks"]


async def test_the_basic_definition_passes_every_check(client: AsyncClient) -> None:
    res = await client.post("/v1/workflows/definitions/validate", json={"yaml": BASIC.read_text()})
    assert res.json()["data"] == {
        "ok": True,
        "workflowId": "refund_check",
        "digest": res.json()["data"]["digest"],
        "checks": [],
    }


def named(workflow_id: str, name: str) -> dict[str, Any]:
    return basic() | {"id": workflow_id, "name": name}


async def test_the_list_shows_each_workflow_at_its_latest_version_with_search_and_status(client: AsyncClient) -> None:
    await client.post("/v1/workflows/definitions", json={"definition": named("refund_a", "Refund A")})
    await client.post("/v1/workflows/definitions", json={"definition": named("refund_a", "Refund A, renamed")})
    await client.post("/v1/workflows/definitions", json={"definition": named("card_b", "Card dispute B")})
    # Dev auto-approve takes the publish request live at once.
    assert (await client.post("/v1/workflows/definitions/card_b/publish-requests", json={})).status_code == 201
    started = await client.post("/v1/runs", json={"workflowId": "card_b", "input": {"customerId": "C1", "amount": 5}})
    assert started.status_code == 202, started.text
    listed = (await client.get("/v1/workflows/definitions")).json()["data"]
    rows = {r["workflowId"]: r for r in listed["data"]}
    assert (rows["refund_a"]["version"], rows["refund_a"]["name"], rows["refund_a"]["status"]) == (
        2,
        "Refund A, renamed",
        "draft",
    )
    assert (rows["card_b"]["status"], rows["card_b"]["runs"], rows["card_b"]["liveVersion"]) == ("live", 1, 1)
    assert listed["facets"]["status"] == {"draft": 1, "live": 1}
    found = (await client.get("/v1/workflows/definitions", params={"search": "dispute"})).json()["data"]["data"]
    assert [r["workflowId"] for r in found] == ["card_b"]
    drafts = (await client.get("/v1/workflows/definitions", params={"status": "draft"})).json()["data"]
    assert [r["workflowId"] for r in drafts["data"]] == ["refund_a"]
    # Facets count before the status filter, so the other view's number stays on its tab.
    assert drafts["facets"]["status"] == {"draft": 1, "live": 1}
    paged = (await client.get("/v1/workflows/definitions", params={"pageSize": 1})).json()["data"]
    assert len(paged["data"]) == 1 and paged["pagination"]["total"] == 2


async def test_a_draft_is_deleted_and_a_workflow_that_has_run_is_kept(client: AsyncClient) -> None:
    await client.post("/v1/workflows/definitions", json={"definition": named("draft_c", "Draft C")})
    await client.post("/v1/workflows/definitions", json={"definition": named("live_d", "Live D")})
    await client.post("/v1/workflows/definitions/live_d/publish-requests", json={})
    await client.post("/v1/runs", json={"workflowId": "live_d", "input": {"customerId": "C1", "amount": 5}})
    gone = await client.delete("/v1/workflows/definitions/draft_c")
    assert gone.status_code == 204 and gone.content == b""
    assert (await client.get("/v1/workflows/definitions/draft_c")).status_code == 404
    kept = await client.delete("/v1/workflows/definitions/live_d")
    assert kept.status_code == 409 and kept.json()["error"]["code"] == "definition_has_runs"
    assert (await client.get("/v1/workflows/definitions/live_d")).status_code == 200
    assert (await client.delete("/v1/workflows/definitions/nothing_here")).status_code == 404


async def test_the_workflows_list_holds_v2_beside_v1_on_the_server(client: AsyncClient) -> None:
    await client.post("/v1/workflows/definitions", json={"definition": named("both_e", "Both kinds E")})
    rows = {w["id"]: w for w in (await client.get("/v1/workflows", params={"pageSize": 200})).json()["data"]["data"]}
    v2 = rows["both_e"]
    # A draft has no live version yet, so the row shows version 0, as a v1 draft does.
    assert (v2["engine"], v2["status"], v2["stepCount"], v2["version"]) == ("v2", "draft", len(basic()["nodes"]), 0)
    assert v2["gateCount"] == sum(1 for n in basic()["nodes"] if n["type"] == "ops.flow.humanReview")
    assert {w["engine"] for w in rows.values() if w["id"] != "both_e"} <= {"v1"}
    await client.post("/v1/workflows/definitions/both_e/publish-requests", json={})
    await client.post("/v1/runs", json={"workflowId": "both_e", "input": {"customerId": "C1", "amount": 5}})
    found = (await client.get("/v1/workflows", params={"search": "both kinds"})).json()["data"]["data"]
    assert [(w["id"], w["status"], w["runs24h"]) for w in found] == [("both_e", "live", 1)]
