"""Embeddings through models-service and the one client every non-agent service calls it with. One test per way an
embedding call could go wrong: escape its key or alias kind, lose its spend, come back unreadable, or lose the code a
caller decides on."""

from __future__ import annotations

import asyncio
import math
from typing import Any

import httpx
import pytest

from ops_service_kit.model_calls import IngestModel, ModelCallError, ModelCalls
from ops_service_kit.scripted_vectors import scripted_vector

from .conftest import Models


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True)) / (math.hypot(*a) * math.hypot(*b))


async def test_an_embedding_alias_answers_vectors_at_the_width_asked_and_records_its_spend(models: Models) -> None:
    key_id, secret = await models.key(budget="5")
    calls = ModelCalls(models.client, secret)
    texts = ["How do I report a late home insurance claim?", "Early repayment charges on a personal loan"]
    done = await calls.embed(texts, alias="bank-embed", width=64, tenant="local", step="kb:test")
    assert [len(v) for v in done.vectors] == [64, 64]
    assert done.input_tokens == sum(len(t.split()) for t in texts)
    [row] = await models.calls(key_id)
    assert (row["outcome"], row["alias"], row["inputTokens"], row["outputTokens"]) == ("ok", "bank-embed", 16, 0)
    assert await models.spent(key_id) > 0


async def test_a_chat_alias_is_refused_for_embeddings_and_an_embedding_alias_for_chat(models: Models) -> None:
    key_id, secret = await models.key(budget="5")
    with pytest.raises(ModelCallError) as refused:
        await ModelCalls(models.client, secret).embed(
            ["x y"], alias="bank-standard", width=None, tenant="local", step="s"
        )
    assert (refused.value.code, refused.value.status) == ("alias_kind_mismatch", 400)
    chat = await models.complete(secret, alias="bank-embed")
    assert chat.status_code == 400 and chat.json()["error"]["code"] == "alias_kind_mismatch"
    assert [c["reason"] for c in await models.calls(key_id)] == ["alias_kind_mismatch", "alias_kind_mismatch"]


async def test_a_refusal_keeps_models_service_code_for_the_caller(models: Models) -> None:
    _, secret = await models.key(budget="0")
    with pytest.raises(ModelCallError) as refused:
        await ModelCalls(models.client, secret).embed(["a b"], alias="bank-embed", width=8, tenant="local", step="s")
    assert (refused.value.code, refused.value.status) == ("key_budget_exhausted", 429)


async def test_an_answer_with_too_few_vectors_is_an_error_not_a_short_list() -> None:
    def short(request: httpx.Request) -> httpx.Response:
        one = {"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}
        return httpx.Response(200, json={"object": "list", "model": "m", "data": [one], "usage": {"prompt_tokens": 2}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(short), base_url="http://models") as http:
        with pytest.raises(ModelCallError) as unread:
            await ModelCalls(http, "mk").embed(["a", "b"], alias="bank-embed", width=2, tenant="t", step="s")
    assert unread.value.code == "models_answer_unreadable"


def test_scripted_vectors_put_texts_that_share_words_closer_than_unrelated_ones() -> None:
    claim = scripted_vector("Can I still claim after the 30 day window?", 1536)
    late = scripted_vector("Claims reported late, after the notification window", 1536)
    loan = scripted_vector("Early repayment charge on a personal loan", 1536)
    assert scripted_vector("Can I still claim after the 30 day window?", 1536) == claim
    assert _cosine(claim, late) > _cosine(claim, loan) + 0.25


class _Bridge(httpx.BaseTransport):
    """A blocking transport that hands each request to the async app on the test's own event loop, so the ingestion
    client, which runs in a worker thread, reaches the real models-service app."""

    def __init__(self, inner: httpx.AsyncBaseTransport, loop: asyncio.AbstractEventLoop) -> None:
        self.inner, self.loop = inner, loop

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        async def send() -> httpx.Response:
            body = await self.inner.handle_async_request(request)
            content = await body.aread()
            return httpx.Response(body.status_code, headers=body.headers, content=content)

        return asyncio.run_coroutine_threadsafe(send(), self.loop).result(timeout=30)


async def test_the_ingestion_client_answers_text_and_counts_its_calls_and_tokens(models: Models) -> None:
    key_id, secret = await models.key(budget="5")
    transport = httpx.ASGITransport(app=models.app)
    sync = httpx.Client(transport=_Bridge(transport, asyncio.get_running_loop()), base_url="http://models")
    ingest = IngestModel(sync, secret, tenant="local", step="kb:questions")
    answer: Any = await asyncio.to_thread(
        ingest.complete, "Write three questions this passage answers.", alias="bank-standard", max_tokens=200
    )
    assert answer == "scripted reply from scripted-standard"
    assert (ingest.calls, ingest.input_tokens, ingest.output_tokens) == (1, 6, 4)
    [row] = await models.calls(key_id)
    assert (row["outcome"], row["stepId"]) == ("ok", "kb:questions")
