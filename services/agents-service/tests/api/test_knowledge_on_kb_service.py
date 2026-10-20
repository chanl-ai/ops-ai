"""Chat knowledge on kb-service (c-056 T005), by failure mode: a reply citing kb-service's passage without its page and
section, a thread opened on a knowledge base the agent is not granted, a turn searching a knowledge base taken from the
agent after the thread was opened (kb-service searches whatever ids it is sent), and kb-service being down failing the
reply instead of answering without citations."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_service_kit.contract import response_checker
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, scripted_model, sse_events

PASSAGE = {
    "kbId": "kb_people",
    "itemId": "itm_wire",
    "version": "v2",
    "title": "Wire Transfer Policy",
    "section": "3 Limits > Personal accounts",
    "page": 3,
    "snippet": "The daily wire limit for a personal account is $10,000.",
    "text": "The daily wire limit for a personal account is $10,000.",
    "score": 0.8,
}


@dataclass
class FakeKb:
    """kb-service's knowledge routes for services: two knowledge bases, one passage; `down` answers 503."""

    searched: list[list[str]] = field(default_factory=list[list[str]])
    down: bool = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            return httpx.Response(503, json={"success": False})
        assert request.headers["authorization"].startswith("Bearer "), "a service token"
        if request.url.path == "/v1/knowledge-bases/refs":
            bases = [{"id": "kb_people", "name": "People policies"}, {"id": "kb_treasury", "name": "Treasury"}]
            return httpx.Response(200, json={"success": True, "data": bases})
        body = json.loads(request.content)
        self.searched.append(body["kbIds"])
        return httpx.Response(200, json={"success": True, "data": {"passages": [PASSAGE]}})


@pytest.fixture
async def kb_app() -> AsyncIterator[tuple[AsyncClient, FakeKb, Any]]:
    kb = FakeKb()
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED)
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    kb_http = httpx.AsyncClient(transport=httpx.MockTransport(kb.handle), base_url="http://kb")
    app = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        kb_client=kb_http,
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", event_hooks={"response": [response_checker(app)]}
        ) as client,
    ):
        yield client, kb, app.state.runtime


async def thread(client: AsyncClient, kb_ids: list[str]) -> httpx.Response:
    return await client.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": kb_ids})


async def ask(client: AsyncClient, thread_id: str) -> list[dict[str, Any]]:
    r = await client.post(
        f"/chat/threads/{thread_id}/messages",
        json={"content": "What is the daily wire limit for a personal account?"},
        headers={"Accept": "text/event-stream"},
    )
    assert r.status_code == 200, r.text
    return sse_events(r.text)


async def test_a_reply_cites_kb_services_passage_with_page_and_section(kb_app: tuple[AsyncClient, FakeKb, Any]) -> None:
    client, kb, _ = kb_app
    created = await thread(client, ["kb_people"])
    assert created.status_code == 201 and created.json()["data"]["kbNames"] == ["People policies"], created.text
    events = await ask(client, created.json()["data"]["id"])
    citations = next(e for e in events if e["type"] == "citations")["citations"]
    assert (citations[0]["documentId"], citations[0]["page"], citations[0]["section"], citations[0]["version"]) == (
        "itm_wire",
        3,
        "3 Limits > Personal accounts",
        "v2",
    )
    assert kb.searched == [["kb_people"]]


async def test_a_thread_cannot_open_on_a_knowledge_base_the_agent_is_not_granted(
    kb_app: tuple[AsyncClient, FakeKb, Any],
) -> None:
    client, _, _ = kb_app
    r = await thread(client, ["kb_treasury"])
    assert r.status_code == 422 and "cannot search Treasury" in r.json()["error"]["message"], r.text
    unknown = await thread(client, ["kb_nope"])
    assert unknown.status_code == 422, unknown.text


async def test_a_grant_taken_away_after_the_thread_opened_is_not_searched(
    kb_app: tuple[AsyncClient, FakeKb, Any],
) -> None:
    client, kb, rt = kb_app
    created = (await thread(client, ["kb_people"])).json()["data"]
    agent = rt.catalog.agent("ag_fraud")
    rt.catalog.put_agent(
        agent.model_copy(update={"default_kb_ids": [k for k in agent.default_kb_ids if k != "kb_people"]})
    )
    events = await ask(client, created["id"])
    assert kb.searched == [], "kb-service was asked to search a knowledge base the agent no longer holds"
    assert not any(e["type"] == "citations" and e["citations"] for e in events)
    text = "".join(e.get("delta", "") for e in events if e["type"] == "text")
    assert "no longer available" in text, "the reply says the knowledge is gone instead of answering uncited"
    done = events[-1]["message"]
    assert done.get("noAnswer") is True, done


async def test_kb_service_down_answers_without_citations(kb_app: tuple[AsyncClient, FakeKb, Any]) -> None:
    client, kb, _ = kb_app
    created = (await thread(client, ["kb_people"])).json()["data"]
    kb.down = True
    events = await ask(client, created["id"])
    assert events[-1]["type"] == "done", events[-1]
    assert not any(e["type"] == "citations" and e["citations"] for e in events)
    refused = await thread(client, ["kb_people"])
    assert refused.status_code == 503 and refused.json()["error"]["code"] == "knowledge_unavailable", refused.text


async def test_the_test_panel_names_bases_as_kb_service_does_and_by_id_while_it_is_down(
    kb_app: tuple[AsyncClient, FakeKb, Any],
) -> None:
    # c-170 review: the panel named bases from the agents seed ("Fraud & payments"), not as kb-service names them.
    client, kb, _ = kb_app
    question = {"message": "What is the daily wire limit for a personal account?"}
    r = await client.post("/v1/agents/ag_fraud/test", json=question)
    assert r.status_code == 200, r.text
    t = r.json()["data"]
    assert {k["id"]: k["name"] for k in t["knowledgeBases"]}.get("kb_people") == "People policies", t["knowledgeBases"]
    assert {c["kbName"] for c in t["citations"]} == {"People policies"}, t["citations"]
    kb.down = True
    down = await client.post("/v1/agents/ag_fraud/test", json=question)
    assert down.status_code == 200, down.text
    assert {k["id"]: k["name"] for k in down.json()["data"]["knowledgeBases"]}.get("kb_people") == "kb_people"
