"""/v1/agents over the registry. Failure modes: a seeded agent stops serving once it is a row; a draft edit leaks
into what is live; a publish does not reach chat or the agent's graph; a publish of the wrong version or a second
open request goes through; pause leaves the agent startable; a restart forgets what was published; the test turn acts
on a write tool instead of stopping at its gate."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.api.app import create_app
from ops_agents.api.model_aliases import HttpModelAliases, ModelsUnavailable, chat_aliases
from ops_agents.store.graphs import metadata
from ops_service_kit.settings import Settings

from ..conftest import SEED, FakeGraphModels, scripted_model, sse_events
from ..contract import response_checker

FRAUD = "ag_fraud"


def _ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"]


@asynccontextmanager
async def _app(db: str, **settings: Any) -> AsyncGenerator[AsyncClient]:
    """The app on a SQLite file, so a second app on the same file is a restart."""
    url = f"sqlite+aiosqlite:///{db}"
    engine = create_async_engine(url)
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    app = create_app(
        Settings(database_url=url, seed_dir=SEED, **settings),
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t", event_hooks={"response": [response_checker(app)]}
        ) as c,
    ):
        yield c


async def _agent(client: AsyncClient, aid: str) -> dict[str, Any]:
    r = await client.get(f"/v1/agents/{aid}")
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _create(client: AsyncClient, name: str = "Payee Checker") -> dict[str, Any]:
    r = await client.post("/v1/agents", json={"name": name, "role": "Checks new payees"})
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def _publish(client: AsyncClient, aid: str, version: int) -> Any:
    return await client.post(f"/v1/agents/{aid}/publish-requests", json={"version": version, "note": "go"})


async def _graph_reply(client: AsyncClient, graph: str, message: str) -> str:
    tid = (await client.post("/v1/threads", json={"graph": graph})).json()["data"]["threadId"]
    raw = (await client.post(f"/v1/threads/{tid}/runs/stream", json={"input": {"message": message}})).text
    assert sse_events(raw)[-1]["event"] == "end", raw
    return (await client.get(f"/v1/threads/{tid}/state")).json()["data"]["values"]["reply"]


async def test_seeded_agents_are_published_rows_and_still_serve_chat(client: AsyncClient) -> None:
    body = (await client.get("/v1/agents?page=1&pageSize=25")).json()["data"]
    assert {a["id"] for a in body["data"]} == {"ag_fraud", "ag_dispute", "ag_branch"}
    assert body["pagination"]["total"] == 3 and body["facets"]["availability"] == {"published": 3}
    fraud = await _agent(client, FRAUD)
    assert fraud["publishedVersion"] == fraud["version"] == 7 and fraud["toolIds"] == [
        "lookup_account",
        "place_wire_hold",
    ]
    chat_ids = {a["id"] for a in (await client.get("/chat/agents")).json()["data"]}
    assert chat_ids == {"ag_fraud", "ag_dispute", "ag_branch"}
    graphs = {g["name"]: g for g in (await client.get("/v1/graphs")).json()["data"]}
    assert graphs["agent:ag_fraud"]["title"] == "Wire Fraud Sentinel"


async def test_a_draft_edit_changes_nothing_live_until_published(client: AsyncClient) -> None:
    r = await client.patch(f"/v1/agents/{FRAUD}", json={"instructions": "Answer only in French.", "note": "fr"})
    assert r.status_code == 200, r.text
    assert (r.json()["data"]["version"], r.json()["data"]["publishedVersion"]) == (8, 7)
    chat = {a["id"]: a for a in (await client.get("/chat/agents")).json()["data"]}
    assert chat[FRAUD]["version"] == 7
    versions = (await client.get(f"/v1/agents/{FRAUD}/versions")).json()["data"]
    assert [(v["version"], v["state"]) for v in versions] == [(8, "draft"), (7, "published")]
    assert versions[0]["changes"] == ["Changed instructions"]

    review = await _publish(client, FRAUD, 8)
    assert review.status_code == 201, review.text
    assert review.json()["data"]["kind"] == "agent_publish" and review.json()["data"]["status"] == "approved"
    chat = {a["id"]: a for a in (await client.get("/chat/agents")).json()["data"]}
    assert chat[FRAUD]["version"] == 8
    states = [v["state"] for v in (await client.get(f"/v1/agents/{FRAUD}/versions")).json()["data"]]
    assert states == ["published", "superseded"]


async def test_created_agent_serves_only_after_publish(client: AsyncClient) -> None:
    a = await _create(client)
    assert a["availability"] == "not_published" and a["version"] == 1 and a["slug"] == "payee-checker"
    graphs = {g["name"] for g in (await client.get("/v1/graphs")).json()["data"]}
    assert f"agent:{a['id']}" not in graphs
    assert (await client.post("/v1/threads", json={"graph": f"agent:{a['id']}"})).status_code == 400

    assert (await _publish(client, a["id"], 1)).status_code == 201
    a = await _agent(client, a["id"])
    assert a["availability"] == "published" and a["wrapperWorkflowId"] == f"agent:{a['id']}"
    assert await _graph_reply(client, f"agent:{a['id']}", "hello") == "I could not find that."
    chat = await client.post("/chat/threads", json={"agentId": a["id"], "kbIds": []})
    assert chat.status_code in (200, 201), chat.text
    # One thread on its graph and one chat: both count.
    assert (await _agent(client, a["id"]))["tasks24h"] == 2


async def test_publish_refuses_an_old_version_and_a_second_open_request(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite"), registry_auto_approve=False) as client:
        a = await _create(client)
        await client.patch(f"/v1/agents/{a['id']}", json={"role": "Checks payees twice"})
        r = await _publish(client, a["id"], 1)
        assert r.status_code == 422 and r.json()["error"]["code"] == "not_newest_draft"

        first = await _publish(client, a["id"], 2)
        assert first.status_code == 201 and first.json()["data"]["status"] == "pending"
        assert (await _agent(client, a["id"]))["availability"] == "not_published"
        second = await _publish(client, a["id"], 2)
        assert second.status_code == 409 and second.json()["error"]["code"] == "review_open"
        states = [v["state"] for v in (await client.get(f"/v1/agents/{a['id']}/versions")).json()["data"]]
        assert states == ["in_review", "superseded"]


async def test_pause_stops_new_threads_and_resume_serves_again(client: AsyncClient) -> None:
    never = await _create(client, "Never Published")
    r = await client.post(f"/v1/agents/{never['id']}/paused", json={"paused": True})
    assert r.status_code == 409

    r = await client.post(f"/v1/agents/{FRAUD}/paused", json={"paused": True})
    assert r.json()["data"]["availability"] == "paused"
    paused = await client.post("/v1/threads", json={"graph": f"agent:{FRAUD}"})
    assert paused.status_code == 409 and paused.json()["error"]["code"] == "agent_paused"
    assert FRAUD not in {a["id"] for a in (await client.get("/chat/agents")).json()["data"]}

    await client.post(f"/v1/agents/{FRAUD}/paused", json={"paused": False})
    assert (await client.post("/v1/threads", json={"graph": f"agent:{FRAUD}"})).status_code == 201


async def test_restore_copies_into_a_new_draft_and_delete_takes_the_agent_down(client: AsyncClient) -> None:
    await client.patch(f"/v1/agents/{FRAUD}", json={"instructions": "Changed."})
    r = await client.post(f"/v1/agents/{FRAUD}/versions/7/restore")
    a = r.json()["data"]
    assert (a["version"], a["publishedVersion"]) == (9, 7) and a["instructions"].startswith("You are Wire Fraud")

    assert (await client.delete(f"/v1/agents/{FRAUD}")).status_code == 204
    assert (await client.get(f"/v1/agents/{FRAUD}")).status_code == 404
    assert "agent:ag_fraud" not in {g["name"] for g in (await client.get("/v1/graphs")).json()["data"]}


async def test_test_turn_stops_at_the_gate_on_a_write_tool(client: AsyncClient) -> None:
    r = await client.post(f"/v1/agents/{FRAUD}/test", json={"message": "Hold wire W-88213 for 24 hours"})
    assert r.status_code == 200, r.text
    turn = r.json()["data"]
    assert turn["wouldPause"]["reviewers"], turn
    assert all(c["name"] != "place_wire_hold" or not c["output"] for c in turn["toolCalls"]), turn


async def test_what_was_published_survives_a_restart(tmp_path: Path) -> None:
    db = str(tmp_path / "db.sqlite")
    async with _app(db) as c:
        created = await _create(c)
        assert (await _publish(c, created["id"], 1)).status_code == 201
        await c.post("/v1/agents/ag_branch/paused", json={"paused": True})
    async with _app(db) as c:
        graphs = {g["name"] for g in (await c.get("/v1/graphs")).json()["data"]}
        assert f"agent:{created['id']}" in graphs and "agent:ag_branch" not in graphs
        assert (await _agent(c, "ag_branch"))["availability"] == "paused"
        assert (await _agent(c, created["id"]))["availability"] == "published"


async def test_tool_ids_come_from_the_catalogue_listing(client: AsyncClient) -> None:
    tools = {t["id"]: t for t in (await client.get("/v1/tools")).json()["data"]}
    assert tools["place_wire_hold"]["access"] == "money_movement" and tools["place_wire_hold"]["approval"]
    r = await client.patch(f"/v1/agents/{FRAUD}", json={"toolIds": ["tl_1"]})
    assert r.status_code == 400 and r.json()["error"]["code"] == "unknown_tool"
    r = await client.patch(f"/v1/agents/{FRAUD}", json={"toolIds": ["lookup_account"]})
    assert r.status_code == 200 and r.json()["data"]["toolIds"] == ["lookup_account"]


def _models_service() -> httpx.AsyncClient:
    """A stand-in models-service that serves one chat alias besides the runtime's."""

    def answer(request: httpx.Request) -> httpx.Response:
        rows = [{"name": "bank-standard", "kind": "chat"}, {"name": "bank-embed", "kind": "embedding"}]
        return httpx.Response(200, json={"success": True, "data": rows})

    return httpx.AsyncClient(transport=httpx.MockTransport(answer), base_url="http://models")


async def test_an_agents_model_alias_is_checked_at_publish_and_used_by_its_turns(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}"
    engine = create_async_engine(url)
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    settings = Settings(database_url=url, seed_dir=SEED, models_url="http://models")
    app = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        models_client=_models_service(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        unset = await _create(c, "No Alias")
        turn = _ok(await c.post(f"/v1/agents/{unset['id']}/test", json={"message": "hello"}))
        assert turn["model"] == settings.model_alias, "an agent that names no alias runs on the runtime's"

        named = await _create(c, "Named Alias")
        await c.patch(f"/v1/agents/{named['id']}", json={"model": "bank-embed"})
        refused = await _publish(c, named["id"], 2)
        assert refused.status_code == 422 and refused.json()["error"]["code"] == "unknown_model_alias", refused.text

        await c.patch(f"/v1/agents/{named['id']}", json={"model": "bank-standard"})
        assert (await _publish(c, named["id"], 3)).status_code == 201
        turn = _ok(await c.post(f"/v1/agents/{named['id']}/test", json={"message": "hello"}))
        assert turn["model"] == "bank-standard", "the agent's own alias, not the runtime's"


async def test_the_alias_picker_lists_exactly_what_publish_accepts(client: AsyncClient, tmp_path: Path) -> None:
    alone = _ok(await client.get("/v1/model-aliases"))
    assert alone == [{"name": Settings().model_alias, "kind": "chat"}], "without models-service, the runtime alias"

    url = f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}"
    engine = create_async_engine(url)
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    app = create_app(
        Settings(database_url=url, seed_dir=SEED, models_url="http://models"),
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        models_client=_models_service(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        offered = [a["name"] for a in _ok(await c.get("/v1/model-aliases"))]
        assert offered == ["bank-standard"], "chat aliases only; bank-embed is an embedding alias"
        for name, published in (("bank-standard", 201), ("bank-embed", 422)):
            agent = await _create(c, f"Picker {name}")
            await c.patch(f"/v1/agents/{agent['id']}", json={"model": name})
            assert (await _publish(c, agent["id"], 2)).status_code == published


async def test_models_service_aliases_are_its_chat_aliases_and_an_outage_is_503() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer t"
        rows = [{"name": "bank-standard", "kind": "chat"}, {"name": "bank-embed", "kind": "embedding"}]
        return httpx.Response(200, json={"success": True, "data": rows})

    up = HttpModelAliases(httpx.AsyncClient(transport=httpx.MockTransport(answer), base_url="http://m"), lambda: "t")
    assert await chat_aliases(up) == {"bank-standard"}
    down = HttpModelAliases(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(502)), base_url="http://m"),
        lambda: "t",
    )
    with pytest.raises(ModelsUnavailable):
        await chat_aliases(down)
