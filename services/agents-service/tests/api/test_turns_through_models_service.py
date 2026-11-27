# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
"""Turns through models-service, by failure mode: a turn that runs on the runtime's alias instead of its agent's, a
request without this service's model key, a record that names a different alias or request than models-service
logged, a refusal whose message models-service wrote for a person that the turn drops or replaces, and a turn that
breaks with no code and tells the person the assistant could not be reached."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import httpx
import httpx2
import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.api.app import create_app
from ops_agents.api.deps import Runtime
from ops_agents.store.base import metadata
from ops_engine.store import metadata as engine_metadata
from ops_identity.fastapi import DEV_TENANT
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
        # The refusal's message, as models-service words it; and a body that is not its envelope at all: a proxy's
        # page, or a proxy's JSON with a message and no code.
        self.said: str | None = None
        self.raw: str | None = None
        self.proxy: dict[str, object] | None = None
        # An exception's text for every call to break with: a fault that is no refusal and carries no code.
        self.broken: str | None = None

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.broken is not None:
            raise RuntimeError(self.broken)
        if self.raw is not None:
            return httpx2.Response(502, text=self.raw, headers={"content-type": "text/html"})
        if self.proxy is not None:
            return httpx2.Response(502, json=self.proxy)
        if self.refusal is not None:
            status, code = self.refusal
            said = self.said or f"refused: {code}"
            error = {"code": code, "message": said, "status": status, "requestId": "req_1"}
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
    """models-service's alias list; a budget it holds none of is a 404, a budget put
    is taken, and its call log is empty."""
    rows = [{"name": "bank-standard", "kind": "chat"}, {"name": "bank-reasoning", "kind": "chat"}]

    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/v1/models/budgets/"):
            if request.method == "PUT":
                return httpx.Response(200, json={"success": True, "data": {}})
            return httpx.Response(404, json={"success": False, "error": {"code": "not_found", "status": 404}})
        if request.url.path == "/v1/models/calls":
            return httpx.Response(200, json={"success": True, "data": {"data": [], "pagination": {"hasNext": False}}})
        return httpx.Response(200, json={"success": True, "data": rows})

    return httpx.AsyncClient(transport=httpx.MockTransport(answer), base_url="http://models")


@pytest.fixture
async def stack(tmp_path: Path) -> AsyncIterator[tuple[AsyncClient, Runtime, FakeModelsService]]:
    url = f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}"
    engine = create_async_engine(url)
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
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
    # The tenant whose provider keys and budget the call uses: always named, never an install's default.
    assert sent.headers["x-tenant-id"] == DEV_TENANT


async def test_a_graph_turns_calls_name_its_alias_its_threads_budget_and_a_replay_key(
    stack: tuple[AsyncClient, Runtime, FakeModelsService],
) -> None:
    client, _rt, models = stack
    thread = await new_thread(client)
    await send(client, thread["id"], {"content": "What is the daily wire limit for a personal account?"})
    # The graph turn's requests; the memory extraction after the turn runs outside the graph, with no thread.
    sent = [r for r in models.requests if "x-thread-id" in r.headers]
    # The fake's answer cites none of the thread's passages, so the end check adds one correction call.
    assert len(sent) == 2, sent
    assert {json.loads(r.content)["model"] for r in sent} == {"bank-standard"}
    assert {r.headers["x-thread-id"] for r in sent} == {thread["id"]}
    # The gateway holds the conversation's budget and answers a re-run of the same task from its record.
    assert {r.headers["x-budget-id"] for r in sent} == {f"thread:{thread['id']}"}
    assert all(r.headers["x-replay-key"].startswith(f"turn:{thread['id']}:") for r in sent), sent
    assert {r.headers["x-tenant-id"] for r in sent} == {DEV_TENANT}


@pytest.mark.parametrize(
    ("status", "code", "answered"),
    [
        (429, "rate_limited", 429),
        (429, "key_budget_exhausted", 429),
        (403, "sensitivity_not_cleared", 403),
        (502, "provider_error", 503),
        (502, "provider_auth_failed", 503),
        (429, "provider_rate_limited", 429),
        (504, "provider_timeout", 503),
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
    # The error model's kind and retryable reach the chat, so it offers Try again for a busy model.
    assert (events[-1].get("kind"), events[-1].get("retryable")) == ("upstream", True), events[-1]
    reloaded = (await client.get(f"/chat/threads/{thread['id']}")).json()["data"]
    assert reloaded["messages"][-1]["errorCode"] == "rate_limited", "a reload keeps the refusal's code"


SAID = "The model provider refused the account's key. An account admin checks it on Settings > Model providers."


async def test_the_message_models_service_wrote_reaches_the_test_turn_and_the_chat_reply(
    stack: tuple[AsyncClient, Runtime, FakeModelsService],
) -> None:
    client, _, models = stack
    models.refusal, models.said = (502, "provider_auth_failed"), SAID
    tested = await client.post("/v1/agents/ag_fraud/test", json={"message": "hello"})
    assert tested.json()["error"]["message"] == SAID, tested.text
    thread = await new_thread(client)
    _, events = await send(client, thread["id"], {"content": "What is the daily wire limit for a personal account?"})
    assert (events[-1]["type"], events[-1].get("message")) == ("error", SAID)
    reloaded = (await client.get(f"/chat/threads/{thread['id']}")).json()["data"]
    assert reloaded["messages"][-1]["error"] == SAID, "a reload reads the same sentence as the stream"


BROKEN = "pool exhausted on db-7.internal"


async def test_a_turn_that_breaks_with_no_code_streams_internal_error_and_never_the_exception(
    stack: tuple[AsyncClient, Runtime, FakeModelsService],
) -> None:
    client, _, models = stack
    models.broken = BROKEN
    thread = await new_thread(client)
    raw, events = await send(client, thread["id"], {"content": "What is the daily wire limit for a personal account?"})
    reloaded = (await client.get(f"/chat/threads/{thread['id']}")).json()["data"]
    assert BROKEN in reloaded["messages"][-1]["error"], "the stored message keeps the exception for the builder"
    last = events[-1]
    assert last["type"] == "error" and BROKEN not in last["message"], last
    assert (last.get("code"), last.get("kind"), last.get("retryable")) == ("internal_error", "internal", False), last
    assert BROKEN not in raw, "the stream carries the exception text beside the sentence"


@pytest.mark.parametrize(
    ("raw", "proxy", "leak"),
    [
        ("<html><body>502 Bad Gateway from proxy edge-7</body></html>", None, "edge-7"),
        # A gateway's JSON has a message but no code: it is not models-service's envelope, so its text is not shown.
        (None, {"error": {"message": "upstream connect error to 10.0.0.5:443"}}, "10.0.0.5"),
        (None, {"message": "Service Unavailable at edge-9"}, "edge-9"),
    ],
)
async def test_a_body_that_is_not_models_services_envelope_is_never_shown(
    stack: tuple[AsyncClient, Runtime, FakeModelsService],
    raw: str | None,
    proxy: dict[str, object] | None,
    leak: str,
) -> None:
    client, _, models = stack
    models.raw, models.proxy = raw, proxy
    tested = await client.post("/v1/agents/ag_fraud/test", json={"message": "hello"})
    message = tested.json()["error"]["message"]
    assert leak not in message and "html" not in message, message
    assert message.startswith("The model call was refused"), message


async def test_without_a_models_key_turns_stay_on_the_direct_model(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}")
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
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
