"""A conversation's or run's budget and the replay record, through the routes, by failure mode: two calls at once
both taking a budget's last room; a re-run paying for an answer it already has, or a stream replayed into a different
message; a changed request answered from the old record; a failed call keeping its reservation; another tenant's
budget id reaching that budget; and the closing call used to keep working."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import httpx
import httpx2
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessage

from ops_models.app import create_models_app
from ops_service_kit.contract import response_checker

from .conftest import SERVICE, Models, service_token

Handler = Callable[[httpx.Request], Coroutine[Any, Any, httpx.Response]]
ANSWER = {
    "choices": [{"message": {"role": "assistant", "content": "The dispute is open."}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
}


def _ids() -> tuple[str, str]:
    tag = uuid4().hex[:8]
    return f"thread:th_{tag}", f"turn:th_{tag}:task_1"


async def _budget(client: httpx.AsyncClient, budget_id: str, tenant: str = "local", **caps: Any) -> dict[str, Any]:
    body = {"kind": "thread", "teamId": "team_ops", "createdBy": "tests", **caps}
    r = await client.put(f"/v1/models/budgets/{budget_id}", json=body, headers=service_token(tenant))
    assert r.status_code == 200, r.text
    return await _read(client, budget_id, tenant)


async def _read(client: httpx.AsyncClient, budget_id: str, tenant: str = "local") -> dict[str, Any]:
    r = await client.get(f"/v1/models/budgets/{budget_id}", headers=service_token(tenant))
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _call(secret: str, budget_id: str, replay_key: str, tenant: str = "local", **more: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {secret}",
        "X-Tenant-Id": tenant,
        "X-Budget-Id": budget_id,
        "X-Replay-Key": replay_key,
        **more,
    }


def _ask(alias: str, said: str = "Summarise the dispute for case DSP-2210 please", **more: Any) -> dict[str, Any]:
    return {"model": alias, "messages": [{"role": "user", "content": said}], **more}


@asynccontextmanager
async def _upstream(models: Models, handle: Handler) -> AsyncGenerator[tuple[Models, str, str]]:
    """A priced alias on an OpenAI-compatible connection answered by `handle`, and a model key: (app, alias, secret)."""
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    app = create_models_app(models.engine, provider_secrets={"UPSTREAM_KEY": "sk-upstream"}, upstream=upstream)
    transport = httpx.ASGITransport(app=app)
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(transport=transport, base_url="http://models", event_hooks=hooks) as client:
        conn = {"name": f"up-{uuid4().hex[:8]}", "type": "openai-compatible", "baseUrl": "http://up/v1"}
        made = await client.post("/v1/models/providers", json={**conn, "keyRef": "UPSTREAM_KEY"}, headers=SERVICE)
        alias = f"bank-up-{uuid4().hex[:8]}"
        version = {"providerId": made.json()["data"]["id"], "modelId": "gpt-up", "clearedSensitivity": "internal"}
        priced = {**version, "inputPerMillion": "1000", "outputPerMillion": "1000"}
        r = await client.post("/v1/models/aliases", json={"name": alias, **priced}, headers=SERVICE)
        assert r.status_code == 201, r.text
        on_app = Models(client, models.engine, app)
        _, secret = await on_app.key(budget="5")
        yield on_app, alias, secret


async def test_two_calls_at_once_on_a_budget_with_room_for_one_serve_one(models: Models) -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    async def handle(_: httpx.Request) -> httpx.Response:
        # The first call is with the provider, not yet settled, while the second asks the same budget.
        if not entered.is_set():
            entered.set()
            await release.wait()
        return httpx.Response(200, json=ANSWER)

    async with _upstream(models, handle) as (app, alias, secret):
        budget_id, key = _ids()
        await _budget(app.client, budget_id, maxCalls=1)
        url = "/v1/models/chat/completions"
        first = asyncio.ensure_future(app.client.post(url, json=_ask(alias), headers=_call(secret, budget_id, key)))
        try:
            await asyncio.wait_for(entered.wait(), 10)
            second = await app.client.post(url, json=_ask(alias), headers=_call(secret, budget_id, key + ":b"))
        finally:
            release.set()
        served = await asyncio.wait_for(first, 10)
        after = await _read(app.client, budget_id)
    assert served.status_code == 200, served.text
    assert second.status_code == 429, second.text
    assert second.json()["error"]["code"] == "budget_reached"
    assert second.json()["error"]["details"]["budgetId"] == budget_id
    assert (after["spentCalls"], after["reservedTokens"]) == (1, 0)


async def test_the_same_request_under_one_replay_key_is_answered_once_streamed_or_not(models: Models) -> None:
    key_id, secret = await models.key(budget="5")
    budget_id, key = _ids()
    await _budget(models.client, budget_id, maxCalls=10)
    url = "/v1/models/chat/completions"
    first = await models.client.post(url, json=_ask("bank-standard"), headers=_call(secret, budget_id, key))
    again = await models.client.post(url, json=_ask("bank-standard"), headers=_call(secret, budget_id, key))
    assert again.status_code == 200, again.text
    assert again.headers.get("x-replayed") == "true"
    assert again.json()["choices"] == first.json()["choices"]

    # A streamed reply that called a tool, replayed as chunks an OpenAI client reads back into the same message.
    http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=models.app))
    client = AsyncOpenAI(
        base_url="http://models/v1/models",
        api_key=secret,
        max_retries=0,
        http_client=http,
        default_headers=_call(secret, budget_id, key + ":stream"),
    )
    tools = [{"type": "function", "function": {"name": "lookup_case", "parameters": {"type": "object"}}}]
    messages = [{"role": "user", "content": 'call lookup_case {"case": "DSP-2210"}'}]
    streamed: list[ChatCompletionMessage] = []
    for _ in range(2):
        async with client.chat.completions.stream(model="bank-standard", messages=messages, tools=tools) as s:  # type: ignore[arg-type]
            streamed.append((await s.get_final_completion()).choices[0].message)
    live, replayed = streamed
    assert live.tool_calls, "the scripted model called the tool"
    assert (replayed.content, replayed.tool_calls) == (live.content, live.tool_calls)
    rows = await models.calls(key_id)
    assert sorted((r["outcome"], r["cost"]) for r in rows if r["outcome"] == "replayed") == [
        ("replayed", "0.000000"),
        ("replayed", "0.000000"),
    ]
    assert sum(r["outcome"] == "ok" for r in rows) == 2, "each request reached the provider once"
    assert (await _read(models.client, budget_id))["spentCalls"] == 2


async def test_a_changed_request_under_the_same_replay_key_reaches_the_provider(models: Models) -> None:
    key_id, secret = await models.key(budget="5")
    budget_id, key = _ids()
    await _budget(models.client, budget_id, maxCalls=10)
    url = "/v1/models/chat/completions"
    await models.client.post(url, json=_ask("bank-standard"), headers=_call(secret, budget_id, key))
    changed = _ask("bank-standard", "Summarise the dispute for case DSP-2211 please")
    r = await models.client.post(url, json=changed, headers=_call(secret, budget_id, key))
    assert r.status_code == 200, r.text
    assert "x-replayed" not in r.headers
    assert [row["outcome"] for row in await models.calls(key_id)] == ["ok", "ok"]


async def test_a_provider_failure_gives_its_reservation_back(models: Models) -> None:
    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "upstream fell over"}})

    async with _upstream(models, handle) as (app, alias, secret):
        budget_id, key = _ids()
        before = await _budget(app.client, budget_id, maxCostUsd="5")
        for stream in (False, True):
            body = _ask(alias, stream=stream)
            r = await app.client.post("/v1/models/chat/completions", json=body, headers=_call(secret, budget_id, key))
            assert r.status_code == 502, r.text
        after = await _read(app.client, budget_id)
    held = ("reservedCostUsd", "reservedTokens", "spentCostUsd", "spentCalls")
    assert {k: after[k] for k in held} == {k: before[k] for k in held}


async def test_another_tenants_budget_id_is_not_found_and_reserves_nothing(models: Models) -> None:
    _, secret = await models.key(budget="5")
    budget_id, key = _ids()
    before = await _budget(models.client, budget_id, maxCalls=10)
    other = f"t_{uuid4().hex[:8]}"
    r = await models.client.post(
        "/v1/models/chat/completions", json=_ask("bank-standard"), headers=_call(secret, budget_id, key, other)
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "budget_not_found"
    assert (await models.client.get(f"/v1/models/budgets/{budget_id}", headers=service_token(other))).status_code == 404
    after = await _read(models.client, budget_id)
    assert (after["reservedTokens"], after["spentCalls"]) == (before["reservedTokens"], before["spentCalls"])


async def test_a_second_closing_call_and_a_closing_call_with_tools_are_refused(models: Models) -> None:
    _, secret = await models.key(budget="5")
    budget_id, key = _ids()
    await _budget(models.client, budget_id, maxCalls=1)
    url = "/v1/models/chat/completions"
    spent = await models.client.post(url, json=_ask("bank-standard"), headers=_call(secret, budget_id, key))
    assert spent.status_code == 200, spent.text
    closing = _call(secret, budget_id, key, **{"X-Call-Purpose": "closing"})
    answers: list[httpx.Response] = []
    for said in ("Wrap up the reply", "Wrap up the reply once more"):
        answers.append(await models.client.post(url, json=_ask("bank-standard", said), headers=closing))
    tools = [{"type": "function", "function": {"name": "lookup_case", "parameters": {"type": "object"}}}]
    other = _call(secret, budget_id, key + ":other", **{"X-Call-Purpose": "closing"})
    with_tools = await models.client.post(url, json=_ask("bank-standard", tools=tools), headers=other)
    statuses = [(a.status_code, json.loads(a.text).get("error", {}).get("code")) for a in [*answers, with_tools]]
    assert statuses == [(200, None), (429, "budget_reached"), (429, "budget_reached")]
