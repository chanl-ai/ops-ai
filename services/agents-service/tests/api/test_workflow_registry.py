"""/v1/workflows over the registry. Failure modes: a seeded definition stops round-tripping through the canvas; a
draft becomes startable or changes what is live; validation passes a graph that pins an unpublished agent or has a
step the runtime cannot run; publish does not reach POST /v1/threads; the pointer does not decide a new thread's
version; a paused or deleted workflow still starts threads; the test run stops at its review."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from httpx import AsyncClient

from ops_agents.graphs.definition import WorkflowDefinition

from ..conftest import sse_events
from .test_agent_registry import _app  # pyright: ignore[reportPrivateUsage]

# No wire id: with one the scripted model calls place_wire_hold, whose gate ends the agent step with no text.
EMAIL: dict[str, Any] = {
    "sender": "ana@example.com",
    "subject": "Payee",
    "body": "Is the new payee on account CHQ-2219 fine?",
    "attachments": [],
}


def _ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"]


async def _create(client: AsyncClient, slug: str | None = "wire-fraud-sentinel") -> dict[str, Any]:
    body = {"name": "Payee check", "trigger": "Payee added", "template": "approval", "agentSlug": slug}
    return _ok(await client.post("/v1/workflows", json=body), 201)


async def _draft(client: AsyncClient, wid: str) -> dict[str, Any]:
    return _ok(await client.get(f"/v1/workflows/{wid}"))["draft"]["graph"]


async def _publish(client: AsyncClient, wid: str, graph: dict[str, Any]) -> Any:
    return await client.post(f"/v1/workflows/{wid}/publish-requests", json={"graph": graph, "note": "go"})


async def _start(client: AsyncClient, wid: str) -> tuple[int, dict[str, Any]]:
    r = await client.post("/v1/threads", json={"graph": wid})
    return r.status_code, r.json().get("data") or r.json().get("error")


async def test_seeded_workflows_are_live_and_dispute_email_round_trips(client: AsyncClient) -> None:
    rows = _ok(await client.get("/v1/workflows?page=1&pageSize=25"))
    assert {w["id"] for w in rows["data"]} == {"dispute_email", "levy-intake", "levy-case", "wire_hold_review"}
    assert rows["facets"]["status"] == {"live": 4}
    detail = _ok(await client.get("/v1/workflows/dispute_email"))
    seeded = _ok(await client.get("/v1/graphs/dispute_email/versions"))[-1]
    # Publishing the rendered graph unchanged lands on the seeded digest, so it is the same version, not a new one.
    review = _ok(await _publish(client, "dispute_email", detail["graph"]), 201)
    assert review["publish"]["toVersion"] == seeded["version"], review
    assert review["publish"]["digest"] == seeded["digest"]
    wire = _ok(await client.get("/v1/workflows/wire_hold_review"))
    assert wire["agentSlugs"] == ["wire-fraud-sentinel"] and wire["gateCount"] == 1


async def test_a_draft_cannot_start_and_does_not_change_what_is_live(client: AsyncClient) -> None:
    wf = await _create(client)
    assert wf["status"] == "draft" and wf["version"] == 0
    code, err = await _start(client, wf["id"])
    assert code == 400 and err["code"] == "not_published"

    graph = await _draft(client, wf["id"])
    _ok(await _publish(client, wf["id"], graph), 201)
    graph["nodes"][-1]["data"]["label"] = "Renamed"
    _ok(await client.put(f"/v1/workflows/{wf['id']}/draft", json={"graph": graph}))
    code, thread = await _start(client, wf["id"])
    assert code == 201 and thread["version"] == 1
    detail = _ok(await client.get(f"/v1/workflows/{wf['id']}"))
    assert detail["graph"]["nodes"][-1]["data"]["label"] != "Renamed" and detail["draft"] is not None


async def test_validate_fails_an_unpublished_pin_and_steps_the_runtime_cannot_run(client: AsyncClient) -> None:
    agent = _ok(await client.post("/v1/agents", json={"name": "Fresh", "role": "New"}), 201)
    wf = await _create(client, agent["slug"])
    graph = await _draft(client, wf["id"])
    run = _ok(await client.post(f"/v1/workflows/{wf['id']}/validate", json={"graph": graph, "target": "draft"}))
    failing = {r["caseId"]: r["draft"]["failure"] for r in run["results"] if not r["draft"]["passed"]}
    assert set(failing) == {"agent:agent"} and "no published version" in failing["agent:agent"]
    assert run["summary"]["checksFailing"] == 1
    assert _ok(await client.get(f"/v1/workflows/{wf['id']}/validations/latest"))["id"] == run["id"]
    r = await _publish(client, wf["id"], graph)
    assert r.status_code == 422 and r.json()["error"]["code"] == "checks_failing"

    graph["nodes"].append({"id": "x", "type": "router", "data": {"label": "Route"}})
    graph["edges"] += [{"id": "a", "source": "x", "target": "done"}, {"id": "b", "source": "x", "target": "stopped"}]
    graph["edges"].append({"id": "c", "source": "t", "target": "x"})
    run = _ok(await client.post(f"/v1/workflows/{wf['id']}/validate", json={"graph": graph}))
    assert "node:x" in {r["caseId"] for r in run["results"] if not r["draft"]["passed"]}

    _ok(await client.post(f"/v1/agents/{agent['id']}/publish-requests", json={"version": 1, "note": ""}), 201)
    graph = await _draft(client, wf["id"])
    run = _ok(await client.post(f"/v1/workflows/{wf['id']}/validate", json={"graph": graph}))
    assert run["summary"]["checksFailing"] == 0, run


async def test_the_test_run_goes_through_its_review_to_the_end(client: AsyncClient) -> None:
    wf = await _create(client)
    out = _ok(await client.post(f"/v1/workflows/{wf['id']}/test", json={"email": EMAIL}))
    assert out["status"] == "completed" and out["pausesApproved"] == 1, out
    assert out["visited"] == ["t", "agent", "review", "review__decide", "done"], out
    assert out["output"], "the agent step's reply is the output"
    assert all(t["graph"] != wf["id"] for t in _ok(await client.get("/v1/threads"))), "a test run keeps no thread"


async def test_publish_starts_on_the_pointer_and_pause_and_delete_refuse_new_threads(client: AsyncClient) -> None:
    wf = await _create(client)
    wid = wf["id"]
    graph = await _draft(client, wid)
    review = _ok(await _publish(client, wid, graph), 201)
    assert review["kind"] == "publish_request" and review["status"] == "approved"
    assert wid in {g["name"] for g in _ok(await client.get("/v1/graphs"))}

    graph["nodes"][-1]["data"]["label"] = "Approved v2"
    graph["nodes"].insert(1, {"id": "note", "type": "step", "data": {"label": "Note"}})
    graph["edges"][0] = {"id": "t-note", "source": "t", "target": "note"}
    graph["edges"].append({"id": "note-agent", "source": "note", "target": "agent"})
    assert _ok(await _publish(client, wid, graph), 201)["publish"]["toVersion"] == 2
    versions = _ok(await client.get(f"/v1/workflows/{wid}/versions"))
    assert [(v["version"], v["current"]) for v in versions] == [(2, True), (1, False)]

    code, thread = await _start(client, wid)
    assert code == 201 and thread["version"] == 2
    raw = (await client.post(f"/v1/threads/{thread['threadId']}/runs/stream", json={"input": {"email": EMAIL}})).text
    assert sse_events(raw)[-1]["event"] in ("interrupt", "end"), raw
    runs = _ok(await client.get(f"/v1/workflows/{wid}/runs"))
    assert runs["data"][0]["status"] == "waiting_review" and runs["data"][0]["steps"][-1]["nodeId"] == "review"

    _ok(await client.post(f"/v1/workflows/{wid}/pointer", json={"version": 1}))
    code, thread = await _start(client, wid)
    assert code == 201 and thread["version"] == 1

    _ok(await client.post(f"/v1/workflows/{wid}/status", json={"status": "paused"}))
    code, err = await _start(client, wid)
    assert code == 409 and err["code"] == "workflow_paused"
    assert (await client.delete(f"/v1/workflows/{wid}")).status_code == 204
    assert (await client.get(f"/v1/workflows/{wid}")).status_code == 404
    code, _ = await _start(client, wid)
    assert code == 404


async def test_compiled_agent_step_pins_the_published_version(client: AsyncClient) -> None:
    """A later agent publish does not change a published workflow: the agent's definition is in the digest."""
    v1 = _ok(await client.get("/v1/graphs/wire_hold_review/versions"))[-1]
    await client.patch("/v1/agents/ag_fraud", json={"instructions": "Different."})
    _ok(await client.post("/v1/agents/ag_fraud/publish-requests", json={"version": 8, "note": ""}), 201)
    assert _ok(await client.get("/v1/graphs/wire_hold_review/versions"))[-1]["digest"] == v1["digest"]
    stored = WorkflowDefinition.model_validate(await _definition(client, "wire_hold_review", v1["version"]))
    assess = stored.node("assess")
    assert assess is not None and assess.config["agent"]["version"] == 7


async def _definition(client: AsyncClient, name: str, version: int) -> dict[str, Any]:
    rt = client._transport.app.state.runtime  # type: ignore[attr-defined]  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
    row = await rt.graph_store.version(name, version)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return row["definition"]  # pyright: ignore[reportUnknownVariableType]


async def test_a_restart_keeps_published_and_deleted_workflows_as_they_were(tmp_path: Path) -> None:
    db = str(tmp_path / "db.sqlite")
    async with _app(db) as c:
        kept, gone = await _create(c), await _create(c)
        for wf in (kept, gone):
            _ok(await _publish(c, wf["id"], await _draft(c, wf["id"])), 201)
        assert (await c.delete(f"/v1/workflows/{gone['id']}")).status_code == 204
    async with _app(db) as c:
        ids = {w["id"] for w in _ok(await c.get("/v1/workflows"))["data"]}
        assert kept["id"] in ids and gone["id"] not in ids
        assert (await _start(c, kept["id"]))[0] == 201
        assert (await _start(c, gone["id"]))[0] == 404


def _routed(field: str = "email.subject", default: bool = True) -> dict[str, Any]:
    """Trigger → router: subject "urgent" goes to a review, anything else to done."""

    def n(nid: str, kind: str, **data: Any) -> dict[str, Any]:
        return {"id": nid, "type": kind, "position": {"x": 0, "y": 0}, "data": {"label": nid, **data}}

    routes = {"urgent": {"field": field, "op": "eq", "value": "urgent"}}
    router = n("route", "router", routes=routes, **({"defaultRoute": "other"} if default else {}))
    return {
        "nodes": [n("t", "trigger"), router, n("review", "review"), n("done", "end"), n("stopped", "end")],
        "edges": [
            {"id": "1", "source": "t", "target": "route"},
            {"id": "2", "source": "route", "target": "review", "sourceHandle": "urgent"},
            {"id": "3", "source": "route", "target": "done", "sourceHandle": "other"},
            {"id": "4", "source": "review", "target": "done", "sourceHandle": "approved"},
            {"id": "5", "source": "review", "target": "stopped", "sourceHandle": "rejected"},
        ],
    }


async def test_a_router_routes_by_its_comparisons_and_falls_back_to_its_default(client: AsyncClient) -> None:
    wid = (await _create(client, None))["id"]
    graph = _routed()
    run = _ok(await client.post(f"/v1/workflows/{wid}/validate", json={"graph": graph}))
    assert run["summary"]["checksFailing"] == 0, run
    for subject, path in (
        ("urgent", ["t", "route", "review", "review__decide", "done"]),
        ("hi", ["t", "route", "done"]),
    ):
        out = _ok(
            await client.post(
                f"/v1/workflows/{wid}/test", json={"graph": graph, "email": {**EMAIL, "subject": subject}}
            )
        )
        assert out["visited"] == path, (subject, out)
    assert _ok(await _publish(client, wid, graph), 201)["status"] == "approved"


async def test_a_router_fails_validation_on_an_unknown_field_or_no_default(client: AsyncClient) -> None:
    wid = (await _create(client, None))["id"]
    for graph, expected in ((_routed("amount"), "unknown field amount"), (_routed(default=False), "default route")):
        run = _ok(await client.post(f"/v1/workflows/{wid}/validate", json={"graph": graph}))
        failures = [r["draft"]["failure"] for r in run["results"] if not r["draft"]["passed"]]
        assert any(expected in f for f in failures), failures
        r = await _publish(client, wid, graph)
        assert r.status_code == 422 and r.json()["error"]["code"] == "checks_failing"


async def test_route_fields_list_exactly_what_validation_accepts(client: AsyncClient) -> None:
    vocab = _ok(await client.get("/v1/workflows/route-fields"))
    wid = (await _create(client, None))["id"]
    samples = {"text": "x", "number": 1, "boolean": True}
    for f in vocab["fields"]:
        for op in vocab["ops"]:
            value: Any = [samples[f["type"]]] if op.get("list") else samples[f["type"]]
            graph = _routed()
            graph["nodes"][1]["data"]["routes"]["urgent"] = {"field": f["name"], "op": op["op"], "value": value}
            run = _ok(await client.post(f"/v1/workflows/{wid}/validate", json={"graph": graph}))
            allowed = f["type"] in op["types"]
            assert (run["summary"]["checksFailing"] == 0) == allowed, (f, op, run["results"][-1])
