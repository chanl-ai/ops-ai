"""How a model reply can end without an answer, through the one client and the real models-service app with the
provider faked at its edge: cut off at the output limit, declined, stopped by a content filter, empty, or not in time.
Each reaches the caller as its own code, after the tokens it was billed are counted, so no caller saves an empty
answer and no spend goes unrecorded."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from ops_service_kit.model_calls import IngestModel, ModelCallError, ModelCalls, Usage

from .conftest import Models
from .test_embeddings import Bridge
from .test_provider_failures import provider_rig

USAGE = {"prompt_tokens": 900, "completion_tokens": 400}
CUT = {"id": "c1", "type": "function", "function": {"name": "final_result", "arguments": '{"invoice_no": "NWF-8'}}
SCHEMA = {"type": "object", "properties": {"invoice_no": {"type": "string"}}}


def _reply(message: dict[str, Any], finish: str) -> dict[str, Any]:
    return {"choices": [{"index": 0, "message": {"role": "assistant", **message}, "finish_reason": finish}],
            "usage": USAGE}  # fmt: skip


ENDINGS = {
    "reply_cut_off": _reply({"content": None, "tool_calls": [CUT]}, "length"),
    "reply_declined": _reply({"content": None, "refusal": "I can't help with this document."}, "stop"),
    "reply_filtered": _reply({"content": None}, "content_filter"),
    "reply_empty": _reply({"content": ""}, "stop"),
}


@pytest.mark.parametrize("code", sorted(ENDINGS))
async def test_a_reply_with_no_answer_is_refused_by_its_own_code_and_its_tokens_still_count(
    models: Models, code: str
) -> None:
    limits: list[object] = []

    def handle(request: httpx.Request) -> httpx.Response:
        limits.append(json.loads(request.content).get("max_tokens"))
        return httpx.Response(200, json=ENDINGS[code])

    async for rig in provider_rig(models, handle):
        spent = Usage()
        calls = ModelCalls(rig.models.client, rig.secret, alias=rig.alias)
        with pytest.raises(ModelCallError) as refused:
            await calls.structured("Read the invoice.", "Invoice NWF-88", SCHEMA, tenant="local", step="extract",
                                   max_tokens=4000, usage=spent)  # fmt: skip
        assert refused.value.code == code, refused.value
        assert (spent.calls, spent.input_tokens, spent.output_tokens) == (1, 900, 400), spent
        assert limits == [4000], "the caller's output limit reaches the provider"
        return
    raise AssertionError("no rig")


async def test_models_service_not_answering_in_time_is_its_own_code() -> None:
    def late(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no answer", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(late), base_url="http://models") as http:
        with pytest.raises(ModelCallError) as refused:
            await ModelCalls(http, "mk").structured("s", "u", SCHEMA, tenant="t", step="s")
    assert refused.value.code == "models_timeout"


async def test_ingestion_text_cut_off_at_its_limit_is_refused_not_kept_as_half_an_answer(models: Models) -> None:
    limits: list[object] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        limits.append((sent.get("max_completion_tokens"), sent.get("max_tokens")))
        return httpx.Response(200, json=_reply({"content": "1. Can I claim after"}, "length"))

    async for rig in provider_rig(models, handle):
        transport = httpx.ASGITransport(app=rig.models.app)
        sync = httpx.Client(transport=Bridge(transport, asyncio.get_running_loop()), base_url="http://models")
        ingest = IngestModel(sync, rig.secret, tenant="local", step="kb:questions")
        with pytest.raises(ModelCallError) as refused:
            await asyncio.to_thread(ingest.complete, "Write three questions.", alias=rig.alias, max_tokens=40)
        assert refused.value.code == "reply_cut_off"
        assert (ingest.calls, ingest.input_tokens) == (1, 900), "a billed reply is counted though it is refused"
        assert limits == [(None, 40)], "an uncatalogued server reads max_tokens"
        return
    raise AssertionError("no rig")
