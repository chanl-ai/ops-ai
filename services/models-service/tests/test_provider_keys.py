"""A provider connection's key comes from the Secrets store (c-177), by failure mode: the provider called without the
key Secrets holds, the dev settings key winning over a key an admin saved, a rotation that never reaches the provider,
a read of tools-service on every call, and a deployment outside dev still starting with keys in its settings.
tools-service's secrets route is a fake here; its own tests cover it (tools-service tests/test_secret_values.py)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from ops_identity import ServiceClient
from ops_models.__main__ import provider_keys
from ops_models.app import create_models_app
from ops_models.provider_keys import ProviderKeys
from ops_service_kit.settings import Settings

from .conftest import SERVICE, Models


@dataclass
class Secrets:
    """tools-service's POST /v1/secrets/values for the deployment's tenant: what is stored, and each read."""

    stored: dict[str, str]
    reads: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    def handle(self, request: httpx.Request) -> httpx.Response:
        names = json.loads(request.content)["names"]
        self.reads.append({"names": names, "auth": request.headers.get("authorization", "")})
        missing = [n for n in names if n not in self.stored]
        if missing:
            body = {"success": False, "error": {"code": "not_found", "message": f"Secret {missing[0]} was not found."}}
            return httpx.Response(404, json=body)
        return httpx.Response(200, json={"success": True, "data": {"values": {n: self.stored[n] for n in names}}})

    def client(self) -> ServiceClient:
        http = httpx.AsyncClient(transport=httpx.MockTransport(self.handle), base_url="http://tools")
        return ServiceClient.for_settings(
            Settings(), http, service="models", audience="tools", scopes=["secrets_egress:run"], tenant=lambda: "local"
        )


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _provider(seen: list[str | None]) -> httpx.AsyncClient:
    """An OpenAI-compatible provider that answers any completion and records the credential it was sent."""

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        choice = {"index": 0, "message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}
        usage = {"prompt_tokens": 7, "completion_tokens": 3}
        return httpx.Response(200, json={"id": "up", "object": "chat.completion", "choices": [choice], "usage": usage})

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


@dataclass
class Rig:
    complete: Any
    seen: list[str | None]
    secrets: Secrets
    clock: Clock


async def _rig(models: Models, stored: dict[str, str], fallback: dict[str, str]) -> AsyncIterator[Rig]:
    seen: list[str | None] = []
    secrets, clock = Secrets(stored), Clock()
    keys = ProviderKeys(secrets.client(), fallback, clock=clock)
    app = create_models_app(models.engine, upstream=_provider(seen), provider_keys=keys)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://models") as client:
        conn = {"name": f"openai-{uuid4().hex[:8]}", "type": "openai-compatible", "baseUrl": "http://up/v1"}
        pid = await client.post("/v1/models/providers", json={**conn, "keyRef": "OPENAI_API_KEY"}, headers=SERVICE)
        alias = f"bank-keys-{uuid4().hex[:8]}"
        version = {"name": alias, "providerId": pid.json()["data"]["id"], "modelId": "gpt-up"}
        made = await client.post(
            "/v1/models/aliases", json={**version, "clearedSensitivity": "internal"}, headers=SERVICE
        )
        assert made.status_code == 201, made.text
        _, secret = await models.key(budget="5")
        on_app = Models(client, models.engine, app)

        async def complete() -> httpx.Response:
            return await on_app.complete(secret, alias=alias)

        yield Rig(complete, seen, secrets, clock)


@pytest.fixture
async def saved(models: Models) -> AsyncIterator[Rig]:
    """An admin saved the key in Secrets; the dev settings hold an older one under the same name."""
    async for rig in _rig(models, {"OPENAI_API_KEY": "sk-from-secrets"}, {"OPENAI_API_KEY": "sk-from-env"}):
        yield rig


@pytest.fixture
async def env_only(models: Models) -> AsyncIterator[Rig]:
    """The dev stack's exception: nothing saved in Secrets yet, the key only in settings."""
    async for rig in _rig(models, {}, {"OPENAI_API_KEY": "sk-from-env"}):
        yield rig


async def test_the_provider_gets_the_key_saved_in_secrets_not_the_settings_one(saved: Rig) -> None:
    r = await saved.complete()
    assert r.status_code == 200, r.text
    assert saved.seen == ["Bearer sk-from-secrets"]
    assert [x["names"] for x in saved.secrets.reads] == [["OPENAI_API_KEY"]]
    assert saved.secrets.reads[0]["auth"].startswith("Bearer "), "read as this service, with its own token"


async def test_a_key_is_read_once_a_minute_and_a_rotation_applies_after_it(saved: Rig) -> None:
    await saved.complete()
    await saved.complete()
    assert len(saved.secrets.reads) == 1, "the second call within the minute does not ask tools-service"
    saved.secrets.stored["OPENAI_API_KEY"] = "sk-rotated"
    saved.clock.now += 61
    await saved.complete()
    assert saved.seen[-1] == "Bearer sk-rotated" and len(saved.secrets.reads) == 2


async def test_the_dev_stack_falls_back_to_its_settings_key_while_secrets_has_none(env_only: Rig) -> None:
    r = await env_only.complete()
    assert r.status_code == 200, r.text
    assert env_only.seen == ["Bearer sk-from-env"]


def test_outside_dev_a_key_in_settings_stops_start_up() -> None:
    # Only the fields start-up reads here; a full production Settings needs platform auth and keys this test has not.
    settings = Settings.model_construct(
        environment="production", model_provider_keys={"OPENAI_API_KEY": SecretStr("sk-env")}
    )
    with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
        provider_keys(settings)
