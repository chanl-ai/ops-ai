"""When a model call holds the database, by failure mode: the provider called while a transaction is open, so every
slow model answer holds a pooled connection; a stream's frames sent while the request's transaction is still open; and
the gate or the settle spread over a transaction per statement. A completion and an embedding are one gate
transaction, the provider call with none open, then one settle transaction."""

from __future__ import annotations

import json
import tomllib
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from ops_models.app import create_models_app
from ops_service_kit.contract import response_checker
from ops_service_kit.logging import captured_logging
from ops_service_kit.request_timing import current

from .conftest import ADMIN, SERVICE, Models

BUDGETS = Path(__file__).parents[1] / "budgets.toml"
# (transactions finished, transactions open) at each moment the provider is working.
Seen = list[tuple[str, int, int]]


def _held(seen: Seen, moment: str) -> None:
    timing = current()
    assert timing is not None, "the provider runs inside the request"
    seen.append((moment, timing.db_tx, timing.db_tx_open))


class _Chunks(httpx.AsyncByteStream):
    """A provider stream that notes, at each frame it hands over, what the request holds."""

    def __init__(self, seen: Seen) -> None:
        self.seen = seen

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for i, word in enumerate(["Case", " DSP-2210", " is open"]):
            _held(self.seen, f"frame {i}")
            delta = {"index": 0, "delta": {"content": word}}
            chunk = {"id": "up", "object": "chat.completion.chunk", "choices": [delta]}
            yield f"data: {json.dumps(chunk)}\n\n".encode()
        usage = {"prompt_tokens": 9, "completion_tokens": 3}
        tail: dict[str, object] = {"id": "up", "object": "chat.completion.chunk", "choices": [], "usage": usage}
        yield f"data: {json.dumps(tail)}\n\ndata: [DONE]\n\n".encode()


def _provider(seen: Seen) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        _held(seen, "call")
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            rows = [{"object": "embedding", "index": i, "embedding": [0.1, 0.2]} for i in range(len(body["input"]))]
            return httpx.Response(200, json={"data": rows, "usage": {"prompt_tokens": 4}})
        if body.get("stream"):
            return httpx.Response(200, stream=_Chunks(seen), headers={"content-type": "text/event-stream"})
        message = {"role": "assistant", "content": "Case DSP-2210 is open"}
        usage = {"prompt_tokens": 9, "completion_tokens": 5}
        choice = {"index": 0, "message": message, "finish_reason": "stop"}
        return httpx.Response(200, json={"choices": [choice], "usage": usage})

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


@pytest.mark.parametrize("call", ["completion", "stream", "embedding"])
async def test_the_provider_answers_with_no_transaction_open_between_one_gate_and_one_settle(
    models: Models, call: str
) -> None:
    seen: Seen = []
    app = create_models_app(models.engine, provider_secrets={"UPSTREAM_KEY": "sk-upstream"}, upstream=_provider(seen))
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://models", event_hooks=hooks
    ) as client:
        conn = {"name": f"up-{uuid4().hex[:8]}", "type": "openai-compatible", "baseUrl": "http://up/v1"}
        made = await client.post("/v1/models/providers", json={**conn, "keyRef": "UPSTREAM_KEY"}, headers=ADMIN)
        alias = f"bank-up-{uuid4().hex[:8]}"
        kind = "embedding" if call == "embedding" else "chat"
        version = {"name": alias, "kind": kind, "providerId": made.json()["data"]["id"], "modelId": "gpt-up"}
        r = await client.post("/v1/models/aliases", json={**version, "clearedSensitivity": "internal"}, headers=ADMIN)
        assert r.status_code == 201, r.text
        key_id, secret = await Models(client, models.engine, app).key(budget="5")
        caller = {"Authorization": f"Bearer {secret}", "X-Tenant-Id": "local"}
        if call == "embedding":
            path, body = "/v1/models/embeddings", {"model": alias, "input": ["Is case DSP-2210 open?"]}
        else:
            path = "/v1/models/chat/completions"
            ask = [{"role": "user", "content": "Is it open?"}]
            body = {"model": alias, "messages": ask, "stream": call == "stream"}
        with captured_logging("models-tx") as stream:
            r = await client.post(path, json=body, headers=caller)
        assert r.status_code == 200, r.text
        line = next(json.loads(x) for x in stream.getvalue().splitlines() if '"http.request"' in x)

    assert [s for s in seen if s[0] == "call"] == [("call", 1, 0)], "one gate transaction, closed before the call"
    frames = [s for s in seen if s[0] != "call"]
    assert all(open_ == 0 for _, _, open_ in frames), f"a frame went out with a transaction open: {frames}"
    row = tomllib.loads(BUDGETS.read_text())[f"POST {path}"]
    measured = (line["db.tx_count"], line["db.connection_count"])
    assert measured == (row["transactions"], row["connections"]) == (2, 2), "one gate and one settle transaction"
    calls = (await models.client.get("/v1/models/calls", params={"keyId": key_id}, headers=SERVICE)).json()["data"]
    assert [(c["outcome"], c["inputTokens"]) for c in calls["data"]] == [("ok", 4 if call == "embedding" else 9)]
