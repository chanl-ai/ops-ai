"""GET /v1/workflows/node-types is the one list of node kinds: an editor that draws from it must find each basic type
with its ports, and the route must not be taken for a workflow id by GET /v1/workflows/{workflow_id}."""

from __future__ import annotations

from httpx import AsyncClient


async def test_the_six_basic_types_are_served_with_their_ports(client: AsyncClient) -> None:
    res = await client.get("/v1/workflows/node-types")
    assert res.status_code == 200, res.text
    by_id = {t["id"]: t for t in res.json()["data"]}
    assert {
        "ops.trigger.request",
        "ops.data.set",
        "ops.flow.if",
        "ops.action.tool",
        "ops.flow.humanReview",
        "ops.flow.end",
    } <= set(by_id)
    ports = {i: [p["name"] for p in t["outputs"]] for i, t in by_id.items()}
    assert ports["ops.trigger.request"] == ["payload"]
    assert ports["ops.flow.if"] == ["true", "false"]
    assert ports["ops.action.tool"] == ["ok", "refused", "error"]
    assert ports["ops.flow.humanReview"] == ["approve", "reject"]
    assert by_id["ops.flow.humanReview"]["outputsFrom"] == "options"
    # The route lists the port a review leaves by when it expires, so an editor can draw it (c-261).
    assert by_id["ops.flow.humanReview"]["optionalOutputs"] == [
        {"parameter": "onTimeout", "value": "expire", "port": "timeout"}
    ]
    assert ports["ops.flow.end"] == []
    # A write is sent again only when the gateway proves it never ran it, each time under a new key (c-561).
    assert by_id["ops.action.tool"]["retry"]["attempts"] == 3, "a write gets three attempts at most"
    assert all(p["connection"] == "main" for t in by_id.values() for p in t["outputs"])
