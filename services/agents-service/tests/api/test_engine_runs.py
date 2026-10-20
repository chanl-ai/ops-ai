"""POST /v1/runs only enqueues: a run starts queued with its start row, a repeated run key returns the first run, and
the run detail reads the journal. With no worker in the API process the run stays queued."""

from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient

BASIC = Path(__file__).parents[1] / "fixtures" / "engine" / "basic.yaml"


async def test_a_run_is_queued_once_per_key_and_waits_for_a_worker(client: AsyncClient) -> None:
    assert (await client.post("/v1/workflows/definitions", json={"yaml": BASIC.read_text()})).status_code == 201
    # Dev auto-approve takes the publish request live at once.
    assert (await client.post("/v1/workflows/definitions/refund_check/publish-requests", json={})).status_code == 201
    body = {"workflowId": "refund_check", "input": {"customerId": "C-1", "amount": 250}, "runKey": "mail-1"}
    first = await client.post("/v1/runs", json=body)
    assert first.status_code == 202, first.text
    run = first.json()["data"]
    assert run["status"] == "queued" and run["runId"].startswith("wfrun_")
    again = await client.post("/v1/runs", json=body)
    assert again.status_code == 200 and again.json()["data"]["runId"] == run["runId"]
    listed = (await client.get("/v1/runs?workflowId=refund_check")).json()["data"]["data"]
    assert [r["id"] for r in listed] == [run["runId"]]
    detail = (await client.get(f"/v1/runs/{run['runId']}")).json()["data"]
    assert detail["status"] == "queued" and detail["steps"] == []
    events = await client.get(f"/v1/runs/{run['runId']}/events?follow=false")
    assert events.status_code == 200
    # Not a review yet, and the v1 Reviews list is unchanged by a queued run.
    assert (await client.get(f"/reviews/{run['runId']}")).status_code == 404
    assert (await client.get("/reviews?view=all")).status_code == 200


async def test_an_unknown_workflow_is_not_started(client: AsyncClient) -> None:
    res = await client.post("/v1/runs", json={"workflowId": "nope", "input": {}})
    assert res.status_code == 404


async def test_the_run_list_pages_filters_by_status_and_counts_each_status(client: AsyncClient) -> None:
    # Workflows > Runs reads this list a page at a time; a bare list grew without bound and hid every older run.
    assert (await client.post("/v1/workflows/definitions", json={"yaml": BASIC.read_text()})).status_code == 201
    assert (await client.post("/v1/workflows/definitions/refund_check/publish-requests", json={})).status_code == 201
    for key in ("p-1", "p-2", "p-3"):
        body = {"workflowId": "refund_check", "input": {"customerId": "C-1", "amount": 1}, "runKey": key}
        assert (await client.post("/v1/runs", json=body)).status_code == 202
    first = (await client.get("/v1/runs?workflowId=refund_check&pageSize=2")).json()["data"]
    second = (await client.get("/v1/runs?workflowId=refund_check&pageSize=2&page=2")).json()["data"]
    assert [len(first["data"]), len(second["data"])] == [2, 1]
    assert first["pagination"]["total"] == 3 and first["pagination"]["hasNext"] is True
    assert {r["id"] for r in first["data"]}.isdisjoint({r["id"] for r in second["data"]})
    assert first["facets"]["status"] == {"queued": 3}
    names = {r["workflowName"] for r in first["data"]}
    assert names and None not in names and "refund_check" not in names, "each row names the workflow, not its id"
    none = (await client.get("/v1/runs?workflowId=refund_check&status=succeeded")).json()["data"]
    assert none["data"] == [] and none["pagination"]["total"] == 0 and none["facets"]["status"] == {"queued": 3}
