"""The client agents-service runs on, driven against models-service in process: the OpenAI SDK as agents-service's
loop and one-off calls use it, streamed and not, with a tool turn, so a shape the SDK cannot parse fails here and not
in a live turn."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx
import httpx2
import pytest
from openai import AsyncOpenAI, AsyncStream, RateLimitError
from openai.types.chat import ChatCompletionChunk, ChatCompletionToolParam

from ops_models.app import create_models_app

from .conftest import SERVICE, Models


def _openai(models: Models, secret: str) -> AsyncOpenAI:
    # No retries: a refused call must reach the caller once, not be repeated behind its back.
    # The OpenAI SDK is typed against httpx2, so its client reaches the app over httpx2's own ASGI transport.
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=models.app))
    # As a calling service sends it: the tenant whose provider keys the call uses.
    return AsyncOpenAI(
        base_url="http://models/v1/models",
        api_key=secret,
        max_retries=0,
        http_client=http,
        default_headers={"X-Tenant-Id": "local"},
    )


LOOKUP: ChatCompletionToolParam = {
    "type": "function",
    "function": {"name": "lookup_case", "description": "Looks up the case.", "parameters": {"type": "object"}},
}


class Turn:
    """One agent turn on the OpenAI SDK, the way agents-service's loop runs one: offer `lookup_case`, run each call it
    asks for, ask again with the results, until the model answers in text."""

    def __init__(self, client: AsyncOpenAI, alias: str) -> None:
        self.client, self.alias = client, alias
        self.called: list[str] = []
        self.returned: list[str] = []
        self.input_tokens: int = 0
        self.output_tokens: int = 0

    async def run(self, prompt: str, *, stream: bool) -> str:
        messages: list[Any] = [{"role": "user", "content": prompt}]
        while True:
            text, calls = await (self._streamed(messages) if stream else self._whole(messages))
            if not calls:
                return text
            messages.append({"role": "assistant", "content": text or None, "tool_calls": calls})
            for call in calls:
                self.called.append(call["function"]["name"])
                self.returned.append("case DSP-2210 is open")
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": self.returned[-1]})

    async def _whole(self, messages: list[Any]) -> tuple[str, list[dict[str, Any]]]:
        r = await self.client.chat.completions.create(model=self.alias, messages=messages, tools=[LOOKUP])
        if r.usage:
            self.input_tokens += r.usage.prompt_tokens
            self.output_tokens += r.usage.completion_tokens
        message = r.choices[0].message
        calls = [c.model_dump(include={"id", "type", "function"}) for c in message.tool_calls or []]
        return message.content or "", calls

    async def _streamed(self, messages: list[Any]) -> tuple[str, list[dict[str, Any]]]:
        stream: AsyncStream[ChatCompletionChunk] = await self.client.chat.completions.create(
            model=self.alias,
            messages=messages,
            tools=[LOOKUP],
            stream=True,
            stream_options={"include_usage": True},
        )
        text, calls = "", dict[int, dict[str, Any]]()
        async for chunk in stream:
            if chunk.usage:
                self.input_tokens += chunk.usage.prompt_tokens
                self.output_tokens += chunk.usage.completion_tokens
            for choice in chunk.choices:
                text += choice.delta.content or ""
                for d in choice.delta.tool_calls or []:
                    call = calls.setdefault(
                        d.index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                    )
                    call["id"] = d.id or call["id"]
                    if d.function is not None:
                        call["function"]["name"] += d.function.name or ""
                        call["function"]["arguments"] += d.function.arguments or ""
        return text, [calls[i] for i in sorted(calls)]


def _agent(models: Models, secret: str, alias: str = "bank-standard") -> Turn:
    return Turn(_openai(models, secret), alias)


@pytest.mark.parametrize("stream", [False, True])
async def test_a_text_turn_runs_through_the_openai_client(models: Models, stream: bool) -> None:
    key_id, secret = await models.key(budget="5")
    agent = _agent(models, secret)
    text = await agent.run("Summarise the dispute", stream=stream)
    assert text == "scripted reply from scripted-standard"
    rows = await models.calls(key_id)
    assert [(r["outcome"], r["alias"]) for r in rows] == [("ok", "bank-standard")]
    assert rows[0]["inputTokens"] > 0 and rows[0]["outputTokens"] > 0
    # The caller meters the same tokens models-service charged, streamed or not.
    assert (agent.input_tokens, agent.output_tokens) == (rows[0]["inputTokens"], rows[0]["outputTokens"])


@pytest.mark.parametrize("stream", [False, True])
async def test_a_tool_turn_carries_the_tool_call_and_its_result(models: Models, stream: bool) -> None:
    key_id, secret = await models.key(budget="5")
    agent = _agent(models, secret)
    await agent.run("please call lookup_case", stream=stream)
    assert agent.called == ["lookup_case"] and agent.returned == ["case DSP-2210 is open"]
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
        text = await agent.run("look it up", stream=stream)
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
            listed = (await client.get(f"/v1/models/aliases/{name}/versions", headers=SERVICE)).json()["data"]["data"]
            assert listed[0]["reasoningEffort"] == effort, listed
        _, secret = await models.key(budget="5")
        auth = {"Authorization": f"Bearer {secret}", "X-Tenant-Id": "local"}
        ask = {"messages": [{"role": "tool", "content": "x"}], "stream": stream}
        for body in ({"model": fast}, {"model": fast, "reasoning_effort": "high"}, {"model": plain}):
            r = await client.post("/v1/models/chat/completions", json=ask | body, headers=auth)
            assert r.status_code == 200, r.text
    assert [s.get("reasoning_effort") for s in seen] == ["minimal", "high", None], seen


async def test_a_tool_call_reply_keeps_openais_names_and_values(models: Models) -> None:
    """The wire a client parses, pinned exactly: a typed reply model must not rename, add or drop a key."""
    _, secret = await models.key(budget="5")
    tool = {"type": "function", "function": {"name": "lookup_case", "parameters": {"type": "object"}}}
    body = {"model": "bank-standard", "messages": [{"role": "user", "content": "please call lookup_case"}]}
    headers = {"Authorization": f"Bearer {secret}", "X-Tenant-Id": "local"}
    r = await models.client.post("/v1/models/chat/completions", json={**body, "tools": [tool]}, headers=headers)
    reply = r.json()
    choice = reply["choices"][0]
    call = choice["message"]["tool_calls"][0]
    assert (r.status_code, sorted(reply), sorted(choice), choice["finish_reason"]) == (
        200,
        ["choices", "created", "id", "model", "object", "usage"],
        ["finish_reason", "index", "message"],
        "tool_calls",
    )
    assert (sorted(choice["message"]), sorted(call), call["type"], sorted(call["function"])) == (
        ["content", "role", "tool_calls"],
        ["function", "id", "type"],
        "function",
        ["arguments", "name"],
    )
    assert (call["function"]["name"], sorted(reply["usage"])) == (
        "lookup_case",
        ["completion_tokens", "prompt_tokens", "total_tokens"],
    )
