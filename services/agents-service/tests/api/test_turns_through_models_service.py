# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
"""Turns through models-service, by failure mode: a turn that runs on the runtime's alias instead of its agent's, a
request without this service's model key, and a record that names a different alias or request than models-service
logged."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, TypedDict, cast

import httpx
import httpx2
import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, StateGraph
from pydantic import SecretStr
from pydantic_ai.messages import ModelMessage, ModelRequest, TextPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agent_kernel.models import ModelsServiceModels
from ops_agents.api.app import create_app
from ops_agents.api.deps import Runtime
from ops_agents.api.model_ledger import LedgerSource
from ops_agents.store.graphs import metadata
from ops_agents.store.model_calls import ModelCallLedger
from ops_agents.store.usage import UsageLedger
from ops_metering import PriceTable
from ops_service_kit.settings import Settings
from tests.api.test_chat import new_thread, send
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model

KEY = "mk_test_agents"


class FakeModelsService:
    """Answers OpenAI chat completions, streamed or not, with the alias it was asked for, and keeps each request."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        # (status, code) to refuse every call with, as models-service does for a key over its limit.
        self.refusal: tuple[int, str] | None = None

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.refusal is not None:
            status, code = self.refusal
            error = {"code": code, "message": f"refused: {code}", "status": status, "requestId": "req_1"}
            return httpx2.Response(status, json={"success": False, "error": error})
        body = json.loads(request.content)
        text = f"Answered on {body['model']}."
        usage = {"prompt_tokens": 11, "completion_tokens": 4, "total_tokens": 15}
        head = {"id": "chatcmpl_1", "created": 1, "model": body["model"]}
        if not body.get("stream"):
            message = {"role": "assistant", "content": text}
            choice = {"index": 0, "message": message, "finish_reason": "stop"}
            return httpx2.Response(200, json={**head, "object": "chat.completion", "choices": [choice], "usage": usage})
        chunks: list[dict[str, Any]] = [
            {"choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            {"choices": [], "usage": usage},
        ]
        sse = "".join(f"data: {json.dumps({**head, 'object': 'chat.completion.chunk', **c})}\n\n" for c in chunks)
        return httpx2.Response(200, text=sse + "data: [DONE]\n\n", headers={"content-type": "text/event-stream"})

    def client(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self.handle))


def _aliases() -> httpx.AsyncClient:
    rows = [{"name": "bank-standard", "kind": "chat"}, {"name": "bank-reasoning", "kind": "chat"}]
    answer = httpx.Response(200, json={"success": True, "data": rows})
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda _: answer), base_url="http://models")


@pytest.fixture
async def stack(tmp_path: Path) -> AsyncIterator[tuple[AsyncClient, Runtime, FakeModelsService]]:
    url = f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}"
    engine = create_async_engine(url)
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    models = FakeModelsService()
    settings = Settings(
        database_url=url,
        seed_dir=SEED,
        models_url="http://models",
        models_key=SecretStr(KEY),
        model_alias="bank-standard",
    )
    app = create_app(
        settings,
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        models_client=_aliases(),
        completions_client=models.client(),
        knowledge=fixture_knowledge(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client,
    ):
        yield client, cast(Runtime, app.state.runtime), models


async def test_an_agents_turn_runs_on_its_alias_with_this_services_key(
    stack: tuple[AsyncClient, Runtime, FakeModelsService],
) -> None:
    client, _, models = stack
    body = {"name": "Reasoning Desk", "role": "Answers", "model": "bank-reasoning"}
    created = await client.post("/v1/agents", json=body)
    assert created.status_code == 201, created.text
    agent = created.json()["data"]
    turn = (await client.post(f"/v1/agents/{agent['id']}/test", json={"message": "hello"})).json()["data"]
    assert (turn["model"], turn["reply"]) == ("bank-reasoning", "Answered on bank-reasoning.")
    sent = models.requests[-1]
    assert json.loads(sent.content)["model"] == "bank-reasoning"
    assert sent.headers["authorization"] == f"Bearer {KEY}"
    assert sent.url.path == "/v1/models/chat/completions"


async def test_a_graph_runs_record_and_models_service_name_the_same_alias_and_request(
    stack: tuple[AsyncClient, Runtime, FakeModelsService],
) -> None:
    client, rt, models = stack
    thread = await new_thread(client)
    await send(client, thread["id"], {"content": "What is the daily wire limit for a personal account?"})
    assert rt.graph_store is not None
    rows = [r for r in await ModelCallLedger(rt.graph_store.engine).calls(thread["id"]) if r["kind"] == "model"]
    assert len(rows) == 1 and rows[0]["model_alias"] == "bank-standard"
    # The graph turn's request; the memory extraction after the turn (c-124) runs outside the graph, with no thread.
    sent = next(r for r in reversed(models.requests) if "x-thread-id" in r.headers)
    assert json.loads(sent.content)["model"] == "bank-standard"
    assert sent.headers["x-thread-id"] == thread["id"]
    assert sent.headers["x-request-hash"] == rows[0]["request_hash"]
    assert sent.headers["x-run-id"] == rows[0]["run_id"]


@pytest.mark.parametrize(
    ("status", "code", "answered"),
    [
        (429, "rate_limited", 429),
        (429, "key_budget_exhausted", 429),
        (403, "sensitivity_not_cleared", 403),
        (502, "provider_error", 503),
    ],
)
async def test_a_refusal_answers_the_test_turn_with_its_status_and_code(
    stack: tuple[AsyncClient, Runtime, FakeModelsService], status: int, code: str, answered: int
) -> None:
    client, _, models = stack
    models.refusal = (status, code)
    res = await client.post("/v1/agents/ag_fraud/test", json={"message": "hello"})
    assert (res.status_code, res.json()["error"]["code"]) == (answered, code)
    assert len(models.requests) == 1, "a refusal is never retried"


async def test_a_refusal_ends_a_streamed_turn_with_its_code_and_a_reload_keeps_it(
    stack: tuple[AsyncClient, Runtime, FakeModelsService],
) -> None:
    client, _, models = stack
    models.refusal = (429, "rate_limited")
    thread = await new_thread(client)
    _, events = await send(client, thread["id"], {"content": "What is the daily wire limit for a personal account?"})
    assert (events[-1]["type"], events[-1].get("code")) == ("error", "rate_limited")
    reloaded = (await client.get(f"/chat/threads/{thread['id']}")).json()["data"]
    assert reloaded["messages"][-1]["errorCode"] == "rate_limited", "a reload keeps the refusal's code"


class _Out(TypedDict, total=False):
    replies: list[str]


async def test_a_rerun_of_the_same_task_is_answered_from_the_record_not_models_service(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    models = FakeModelsService()
    source = LedgerSource(
        ModelsServiceModels("http://models", KEY, http_client=models.client()),
        UsageLedger(engine, PriceTable.parse(Settings().prices)),
    )
    model = source.model_for("bank-standard")

    async def answer(state: _Out) -> dict[str, Any]:
        # The same request twice in one task: what a node's re-run after a crash sends.
        request: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart("What is the wire limit?")])]
        replies = [await model.request(request, None, ModelRequestParameters()) for _ in range(2)]
        return {"replies": [str(r.parts[0].content) for r in replies if isinstance(r.parts[0], TextPart)]}

    g = StateGraph(_Out)
    g.add_node("answer", answer)
    g.add_edge(START, "answer")
    out = await g.compile().ainvoke({"replies": []}, {"configurable": {"thread_id": "th_replay", "run_id": "run_1"}})
    assert out["replies"] == ["Answered on bank-standard."] * 2
    assert len(models.requests) == 1, "the second answer came from the record"


async def test_without_a_models_key_turns_stay_on_the_direct_model(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    models = FakeModelsService()
    # models_url alone serves the alias list (publish-time checks); turns need the key too.
    app = create_app(
        Settings(database_url=str(engine.url), seed_dir=SEED, models_url="http://models"),
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        models_client=_aliases(),
        completions_client=models.client(),
        knowledge=fixture_knowledge(),
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client,
    ):
        turn = (await client.post("/v1/agents/ag_fraud/test", json={"message": "hello"})).json()["data"]
    assert turn["reply"] == "I could not find that." and models.requests == []
