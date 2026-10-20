"""The clients agents-service runs on, driven against models-service in process: the OpenAI SDK and Pydantic AI's
OpenAI model, streamed and not, with a tool turn, so a shape the SDK cannot parse fails here and not in a live turn."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx
import httpx2
import pytest
from openai import AsyncOpenAI, RateLimitError
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import RunUsage

from ops_models.app import create_models_app

from .conftest import SERVICE, Models


def _openai(models: Models, secret: str) -> AsyncOpenAI:
    # No retries: a refused call must reach the caller once, not be repeated behind its back.
    # The OpenAI SDK is typed against httpx2, so its client reaches the app over httpx2's own ASGI transport.
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=models.app))
    return AsyncOpenAI(base_url="http://models/v1/models", api_key=secret, max_retries=0, http_client=http)


def _agent(models: Models, secret: str, alias: str = "bank-standard") -> Agent[None, str]:
    model = OpenAIChatModel(alias, provider=OpenAIProvider(openai_client=_openai(models, secret)))
    agent = Agent(model)

    @agent.tool_plain
    def lookup_case() -> str:  # pyright: ignore[reportUnusedFunction]
        """Looks up the case."""
        return "case DSP-2210 is open"

    return agent


@pytest.mark.parametrize("stream", [False, True])
async def test_a_text_turn_runs_through_the_openai_client(models: Models, stream: bool) -> None:
    key_id, secret = await models.key(budget="5")
    agent = _agent(models, secret)
    usage: RunUsage
    if stream:
        async with agent.run_stream("Summarise the dispute") as run:
            text = await run.get_output()
            usage = run.usage
    else:
        result = await agent.run("Summarise the dispute")
        text, usage = result.output, result.usage
    assert text == "scripted reply from scripted-standard"
    rows = await models.calls(key_id)
    assert [(r["outcome"], r["alias"]) for r in rows] == [("ok", "bank-standard")]
    assert rows[0]["inputTokens"] > 0 and rows[0]["outputTokens"] > 0
    # The caller meters the same tokens models-service charged, streamed or not.
    assert (usage.input_tokens, usage.output_tokens) == (rows[0]["inputTokens"], rows[0]["outputTokens"])


@pytest.mark.parametrize("stream", [False, True])
async def test_a_tool_turn_carries_the_tool_call_and_its_result(models: Models, stream: bool) -> None:
    key_id, secret = await models.key(budget="5")
    agent = _agent(models, secret)
    if stream:
        async with agent.run_stream("please call lookup_case") as run:
            await run.get_output()
            messages = run.all_messages()
    else:
        messages = (await agent.run("please call lookup_case")).all_messages()
    called = [p.tool_name for m in messages for p in m.parts if p.part_kind == "tool-call"]
    returned = [p.content for m in messages for p in m.parts if p.part_kind == "tool-return"]
    assert called == ["lookup_case"] and returned == ["case DSP-2210 is open"]
    # The tool call and the reply after its result are two model calls.
    assert [r["outcome"] for r in await models.calls(key_id)] == ["ok", "ok"]


async def test_a_refusal_reaches_the_client_once(models: Models) -> None:
    key_id, secret = await models.key(budget="5", rateLimitPerMinute=1)
    client = _openai(models, secret)
    await client.chat.completions.create(model="bank-standard", messages=[{"role": "user", "content": "hi"}])
    with pytest.raises(RateLimitError) as refused:
        await client.chat.completions.create(model="bank-standard", messages=[{"role": "user", "content": "hi"}])
    assert refused.value.code == "rate_limited"
    assert [r["outcome"] for r in await models.calls(key_id)] == ["denied", "ok"]


async def test_a_stream_is_refused_before_it_starts(models: Models) -> None:
    key_id, secret = await models.key(budget="0")
    with pytest.raises(RateLimitError):
        await _openai(models, secret).chat.completions.create(
            model="bank-standard", messages=[{"role": "user", "content": "hi"}], stream=True
        )
    assert [r["reason"] for r in await models.calls(key_id)] == ["key_budget_exhausted"]


async def test_the_older_path_still_answers(models: Models) -> None:
    _, secret = await models.key(budget="5")
    r = await models.complete(secret)
    assert r.status_code == 200 and r.json()["choices"][0]["finish_reason"] == "stop"


def _upstream(seen: list[dict[str, object]]) -> httpx.AsyncClient:
    """An OpenAI-compatible provider that calls `lookup_case` when offered it, and answers text after the result."""

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"auth": request.headers.get("authorization"), **body})
        answered = body["messages"][-1]["role"] == "tool"
        call = {"id": "call_up_1", "type": "function", "function": {"name": "lookup_case", "arguments": "{}"}}
        if not body.get("stream"):
            message: dict[str, Any] = {"role": "assistant", "content": "done" if answered else None}
            if not answered:
                message["tool_calls"] = [call]
            choice = {"index": 0, "message": message, "finish_reason": "stop" if answered else "tool_calls"}
            usage = {"prompt_tokens": 7, "completion_tokens": 3}
            return httpx.Response(
                200, json={"id": "up", "object": "chat.completion", "choices": [choice], "usage": usage}
            )
        delta = {"content": "done"} if answered else {"tool_calls": [{"index": 0, **call}]}
        chunks: list[dict[str, Any]] = [
            {"object": "chat.completion.chunk", "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
            {"object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
            {"object": "chat.completion.chunk", "choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 3}},
        ]
        sse = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


@pytest.mark.parametrize("stream", [False, True])
async def test_an_openai_compatible_provider_gets_the_tools_and_returns_the_calls(models: Models, stream: bool) -> None:
    seen: list[dict[str, object]] = []
    app = create_models_app(models.engine, provider_secrets={"UPSTREAM_KEY": "sk-upstream"}, upstream=_upstream(seen))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://models") as client:
        conn = {
            "name": f"upstream-{uuid4().hex[:8]}",
            "type": "openai-compatible",
            "baseUrl": "http://up/v1",
            "keyRef": "UPSTREAM_KEY",
        }
        pid = (await client.post("/v1/models/providers", json=conn, headers=SERVICE)).json()["data"]["id"]
        alias = f"bank-up-{uuid4().hex[:8]}"
        version = {"name": alias, "providerId": pid, "modelId": "gpt-up", "clearedSensitivity": "internal"}
        assert (await client.post("/v1/models/aliases", json=version, headers=SERVICE)).status_code == 201
        key_id, secret = await models.key(budget="5")
        agent = _agent(Models(client, models.engine, app), secret, alias=alias)
        if stream:
            async with agent.run_stream("look it up") as run:
                text = await run.get_output()
        else:
            text = (await agent.run("look it up")).output
    assert text == "done"
    # The provider saw its own model id, the tool the agent offered, and the credential models-service holds.
    assert [(s["model"], s["auth"]) for s in seen] == [("gpt-up", "Bearer sk-upstream")] * 2
    assert all("lookup_case" in json.dumps(s["tools"]) for s in seen)
    rows = await models.calls(key_id)
    assert [(r["outcome"], r["inputTokens"], r["outputTokens"]) for r in rows] == [("ok", 7, 3)] * 2


@pytest.mark.parametrize("stream", [False, True])
async def test_an_alias_version_sets_the_reasoning_effort_a_request_leaves_unset(models: Models, stream: bool) -> None:
    # Chat latency on shared, 2026-10-18: gpt-5-nano at its default effort thought for 10 to 24 s before the first
    # word. The alias names the effort; a caller that sets its own keeps it, and an alias without one sends nothing.
    seen: list[dict[str, object]] = []
    app = create_models_app(models.engine, provider_secrets={"UPSTREAM_KEY": "sk-upstream"}, upstream=_upstream(seen))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://models") as client:
        conn = {
            "name": f"up-{uuid4().hex[:8]}",
            "type": "openai-compatible",
            "baseUrl": "http://up/v1",
            "keyRef": "UPSTREAM_KEY",
        }
        pid = (await client.post("/v1/models/providers", json=conn, headers=SERVICE)).json()["data"]["id"]
        fast, plain = f"fast-{uuid4().hex[:8]}", f"plain-{uuid4().hex[:8]}"
        for name, effort in ((fast, "minimal"), (plain, None)):
            version = {"name": name, "providerId": pid, "modelId": "gpt-up", "clearedSensitivity": "internal"}
            made = await client.post(
                "/v1/models/aliases", json=version | ({"reasoningEffort": effort} if effort else {}), headers=SERVICE
            )
            assert made.status_code == 201, made.text
            listed = (await client.get(f"/v1/models/aliases/{name}/versions", headers=SERVICE)).json()["data"]
            assert listed[0]["reasoningEffort"] == effort, listed
        _, secret = await models.key(budget="5")
        auth = {"Authorization": f"Bearer {secret}"}
        ask = {"messages": [{"role": "tool", "content": "x"}], "stream": stream}
        for body in ({"model": fast}, {"model": fast, "reasoning_effort": "high"}, {"model": plain}):
            r = await client.post("/v1/models/chat/completions", json=ask | body, headers=auth)
            assert r.status_code == 200, r.text
    assert [s.get("reasoning_effort") for s in seen] == ["minimal", "high", None], seen
