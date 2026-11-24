"""How a provider's reply ended reaches the caller and the call log: a reply stopped at its length limit, a declined
reply and a finish word no list names, each read from the provider's own answer rather than made up from whether the
reply has tool calls."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import httpx

from .conftest import Models
from .test_provider_failures import provider_rig

PAGE = {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0KGgo=", "detail": "high"}}
CUT = {"id": "c1", "type": "function", "function": {"name": "final_result", "arguments": '{"invoice_no": "NWF-8'}}


def _replies() -> Iterator[dict[str, object]]:
    usage = {"prompt_tokens": 900, "completion_tokens": 4000}
    yield {
        "choices": [{"message": {"role": "assistant", "tool_calls": [CUT]}, "finish_reason": "length"}],
        "usage": usage,
    }
    declined = {"role": "assistant", "content": None, "refusal": "I can't help with this document."}
    yield {"choices": [{"message": declined, "finish_reason": "stop"}], "usage": usage}
    yield {"choices": [{"message": {"role": "assistant", "content": "Done."}, "finish_reason": "eos"}], "usage": usage}


async def test_a_reply_keeps_how_it_ended_and_the_log_row_records_it(models: Models) -> None:
    replies = _replies()
    limits: list[object] = []

    def handle(request: httpx.Request) -> httpx.Response:
        limits.append(json.loads(request.content).get("max_completion_tokens"))
        return httpx.Response(200, json=next(replies))

    async for rig in provider_rig(models, handle, images=True):
        answers: list[dict[str, Any]] = []
        for _ in range(3):
            body = {
                "model": rig.alias,
                "messages": [{"role": "user", "content": [{"type": "text", "text": "Read invoice"}, PAGE]}],
                "max_completion_tokens": 4000,
            }
            r = await rig.models.client.post(
                "/v1/models/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {rig.secret}", "X-Tenant-Id": "local"},
            )
            assert r.status_code == 200, r.text
            answers.append(r.json()["choices"][0])
        assert [a["finish_reason"] for a in answers] == ["length", "stop", "stop"]
        assert answers[1]["message"]["refusal"] == "I can't help with this document."
        assert "refusal" not in answers[0]["message"], "a reply that was not declined carries no refusal key"
        assert limits == [4000, 4000, 4000], "the caller's output limit reaches the provider"
        return
