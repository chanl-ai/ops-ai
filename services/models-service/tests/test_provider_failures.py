"""How a provider's failure reaches the caller, by failure mode: an unreachable provider, one that does not answer in
time, one that refuses the account's key, one that limits calls, one that refuses the request as sent, and one that
fails on its side, each answered with its own code and a sentence saying what to do; a refused stream answered the
same way before it starts; and a provider body that echoes the key never reaching the answer or the call log."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from uuid import uuid4

import httpx
import pytest

from ops_models.app import create_models_app
from ops_service_kit.contract import response_checker

from .conftest import SERVICE, Models

LEAKED_KEY = "sk-live-4f9a0c7d1e2b3a4c5d6e7f80"
ADMIN_FIX = "Settings > Model providers"


@dataclass
class Rig:
    models: Models
    alias: str
    key_id: str
    secret: str

    async def complete(self, *, stream: bool = False) -> httpx.Response:
        body = {"model": self.alias, "messages": [{"role": "user", "content": "Is case DSP-2210 open?"}]}
        return await self.models.client.post(
            "/v1/models/chat/completions",
            json={**body, "stream": stream},
            headers={"Authorization": f"Bearer {self.secret}", "X-Tenant-Id": "local"},
        )


Handler = Callable[[httpx.Request], httpx.Response]


async def _rig(models: Models, handle: Handler) -> AsyncIterator[Rig]:
    """An OpenAI-compatible connection answered by `handle`, an alias on it and a model key."""
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    app = create_models_app(models.engine, provider_secrets={"UPSTREAM_KEY": "sk-upstream"}, upstream=upstream)
    hooks = {"response": [response_checker(app)]}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://models", event_hooks=hooks) as client:
        conn = {"name": f"up-{uuid4().hex[:8]}", "type": "openai-compatible", "baseUrl": "http://up/v1"}
        made = await client.post("/v1/models/providers", json={**conn, "keyRef": "UPSTREAM_KEY"}, headers=SERVICE)
        alias = f"bank-up-{uuid4().hex[:8]}"
        version = {"name": alias, "providerId": made.json()["data"]["id"], "modelId": "gpt-up"}
        r = await client.post("/v1/models/aliases", json={**version, "clearedSensitivity": "internal"}, headers=SERVICE)
        assert r.status_code == 201, r.text
        on_app = Models(client, models.engine, app)
        key_id, secret = await on_app.key(budget="5")
        yield Rig(on_app, alias, key_id, secret)


def _answers(status: int, body: object = None, headers: dict[str, str] | None = None) -> Handler:
    return lambda _: httpx.Response(status, json=body or {"error": {"message": "refused"}}, headers=headers)


def _raises(error: Exception) -> Handler:
    def handle(_: httpx.Request) -> httpx.Response:
        raise error

    return handle


async def _refusal(models: Models, handle: Handler, *, stream: bool = False) -> tuple[httpx.Response, list[str]]:
    async for rig in _rig(models, handle):
        r = await rig.complete(stream=stream)
        return r, [c["reason"] for c in await rig.models.calls(rig.key_id)]
    raise AssertionError("no rig")


async def test_an_unreachable_provider_is_named_as_unreachable(models: Models) -> None:
    r, reasons = await _refusal(models, _raises(httpx.ConnectError("connection refused")))
    error = r.json()["error"]
    assert (r.status_code, error["code"]) == (502, "provider_unreachable"), r.text
    assert "could not be reached" in error["message"] and ADMIN_FIX in error["message"]
    assert "http://up" not in error["message"], "the connection's address stays out of the message"
    assert reasons == ["provider_unreachable"]


async def test_a_provider_that_does_not_answer_in_time_is_a_timeout(models: Models) -> None:
    r, _ = await _refusal(models, _raises(httpx.ReadTimeout("timed out")))
    assert (r.status_code, r.json()["error"]["code"]) == (504, "provider_timeout"), r.text
    assert "in time" in r.json()["error"]["message"]


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("stream", [False, True])
async def test_a_refused_key_says_an_admin_checks_it(models: Models, status: int, stream: bool) -> None:
    r, reasons = await _refusal(models, _answers(status), stream=stream)
    error = r.json()["error"]
    assert (r.status_code, error["code"]) == (502, "provider_auth_failed"), r.text
    assert "key" in error["message"] and ADMIN_FIX in error["message"]
    assert reasons == ["provider_auth_failed"]


async def test_a_provider_rate_limit_is_a_429_with_its_wait(models: Models) -> None:
    r, reasons = await _refusal(models, _answers(429, headers={"Retry-After": "20"}))
    assert (r.status_code, r.json()["error"]["code"]) == (429, "provider_rate_limited"), r.text
    assert r.headers.get("retry-after") == "20", "the caller waits the time the provider named"
    assert reasons == ["provider_rate_limited"]


@pytest.mark.parametrize("status", [400, 404, 422])
async def test_a_request_the_provider_refuses_as_sent_is_a_bad_request(models: Models, status: int) -> None:
    r, _ = await _refusal(models, _answers(status))
    error = r.json()["error"]
    assert (r.status_code, error["code"]) == (502, "provider_bad_request"), r.text
    assert ADMIN_FIX in error["message"]


@pytest.mark.parametrize("status", [500, 503])
async def test_a_failure_on_the_providers_side_says_to_retry(models: Models, status: int) -> None:
    r, _ = await _refusal(models, _answers(status))
    error = r.json()["error"]
    assert (r.status_code, error["code"]) == (502, "provider_error"), r.text
    assert "Retry" in error["message"]


async def test_a_provider_body_that_echoes_the_key_never_reaches_the_answer_or_the_log(models: Models) -> None:
    echoed = {"error": {"message": f"Incorrect API key provided: {LEAKED_KEY}", "code": "invalid_api_key"}}
    async for rig in _rig(models, _answers(401, echoed)):
        r = await rig.complete()
        assert LEAKED_KEY not in r.text and "sk-upstream" not in r.text
        rows = await rig.models.calls(rig.key_id)
        assert LEAKED_KEY not in str(rows)
