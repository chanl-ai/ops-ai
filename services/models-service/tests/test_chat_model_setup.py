"""Choosing the chat model on first run, by failure mode: the chat aliases left on the old model or never created on a
fresh install; a call that goes to the wrong place or with the wrong header for its provider (Anthropic through its
OpenAI-compatible endpoint); a second choice adding a second connection instead of moving the first; someone who is
not an account admin, or a key not saved, changing what chat uses; and an Azure endpoint outside openai.azure.com."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import httpx
import pytest

from ops_identity.fastapi import current_principal
from ops_models.app import create_models_app
from ops_service_kit.contract import response_checker

from .conftest import SERVICE, Models
from .test_provider_keys import people

AZURE = "https://contoso.openai.azure.com"


@dataclass
class Rig:
    client: httpx.AsyncClient
    seen: list[tuple[str, str, str]]
    aliases: tuple[str, str]
    tenant: str
    models: Models
    secret: str

    async def complete(self, alias: str) -> httpx.Response:
        return await self.models.complete(self.secret, alias=alias, **{"X-Tenant-Id": self.tenant})


def _provider(seen: list[tuple[str, str, str]]) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        sent = request.headers.get("authorization") or request.headers.get("api-key") or ""
        model = httpx.Response(200, content=request.content).json().get("model", "")
        seen.append((f"{request.url.host}{request.url.path}", sent, model))
        choice = {"index": 0, "message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}
        usage = {"prompt_tokens": 7, "completion_tokens": 3}
        return httpx.Response(200, json={"id": "up", "object": "chat.completion", "choices": [choice], "usage": usage})

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


@pytest.fixture
async def rig(models: Models) -> AsyncIterator[Rig]:
    seen: list[tuple[str, str, str]] = []
    tenant = f"t_{uuid4().hex[:8]}"
    # Aliases are install-wide; fresh names stand in for `default` and `assistant` so tests do not share them.
    names = (f"chat-{uuid4().hex[:8]}", f"assist-{uuid4().hex[:8]}")
    app = create_models_app(models.engine, upstream=_provider(seen), chat_aliases=names)
    app.dependency_overrides[current_principal] = people(tenant)
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://models", event_hooks=hooks
    ) as client:
        assert (await client.put("/v1/provider-keys/MAIN", json={"value": "sk-good"})).status_code == 200
        on_app = Models(client, models.engine, app)
        _, secret = await on_app.key(budget="5")
        yield Rig(client, seen, names, tenant, on_app, secret)


@pytest.mark.parametrize(
    ("body", "sent_to", "header", "model"),
    [
        ({"provider": "openai", "model": "gpt-4.1-mini"}, "api.openai.com/v1/chat/completions", "Bearer sk-good",
         "gpt-4.1-mini"),
        ({"provider": "anthropic", "model": "claude-sonnet-4-5"}, "api.anthropic.com/v1/chat/completions",
         "Bearer sk-good", "claude-sonnet-4-5"),
        ({"provider": "azure-openai", "model": "chat-prod", "endpoint": AZURE, "apiVersion": "v1"},
         "contoso.openai.azure.com/openai/v1/chat/completions", "sk-good", "chat-prod"),
    ],
)  # fmt: skip
async def test_a_fresh_install_chats_with_the_model_the_admin_picked(
    rig: Rig, body: dict[str, str], sent_to: str, header: str, model: str
) -> None:
    saved = await rig.client.put("/v1/models/chat-model", json={**body, "keyName": "MAIN"})
    assert saved.status_code == 200, saved.text
    for alias in rig.aliases:
        assert (await rig.complete(alias)).status_code == 200
    assert rig.seen == [(sent_to, header, model)] * 2


async def test_a_second_choice_moves_chat_without_a_second_connection(rig: Rig) -> None:
    first = {"provider": "openai", "model": "gpt-4.1-mini", "keyName": "MAIN"}
    assert (await rig.client.put("/v1/models/chat-model", json=first)).status_code == 200
    again = await rig.client.put("/v1/models/chat-model", json={**first, "model": "gpt-4.1"})
    assert again.status_code == 200, again.text
    assert (await rig.complete(rig.aliases[0])).status_code == 200
    assert rig.seen[-1][2] == "gpt-4.1"
    versions = await rig.client.get(f"/v1/models/aliases/{rig.aliases[0]}/versions", headers=SERVICE)
    assert [v["version"] for v in versions.json()["data"]] == [1, 2]
    assert len({v["providerId"] for v in versions.json()["data"]}) == 1


async def test_only_an_account_admin_with_a_saved_key_sets_the_chat_model(rig: Rig) -> None:
    body = {"provider": "openai", "model": "gpt-4.1-mini", "keyName": "MAIN"}
    member = {"X-Team-Id": "team_ops", "X-Role": "viewer"}
    assert (await rig.client.put("/v1/models/chat-model", json=body, headers=member)).status_code == 403
    missing = await rig.client.put("/v1/models/chat-model", json={**body, "keyName": "NOT_SAVED"})
    assert missing.status_code == 404, missing.text
    assert (await rig.client.get(f"/v1/models/aliases/{rig.aliases[0]}/versions", headers=SERVICE)).status_code == 404


async def test_an_azure_endpoint_outside_openai_azure_com_is_refused(rig: Rig) -> None:
    body = {"provider": "azure-openai", "model": "m", "keyName": "MAIN", "endpoint": "https://evil.example"}
    refused = await rig.client.put("/v1/models/chat-model", json={**body, "apiVersion": "v1"})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "endpoint_refused", refused.text


async def test_a_new_chat_model_keeps_the_prices_the_alias_had(rig: Rig) -> None:
    first = {"provider": "openai", "model": "gpt-4.1-mini", "keyName": "MAIN"}
    assert (await rig.client.put("/v1/models/chat-model", json=first)).status_code == 200
    url = f"/v1/models/aliases/{rig.aliases[0]}/versions"
    held = (await rig.client.get(url, headers=SERVICE)).json()["data"][-1]
    price = {"inputPerMillion": "2.5", "outputPerMillion": "10"}
    body = {"providerId": held["providerId"], "modelId": held["modelId"], "clearedSensitivity": "confidential", **price}
    assert (await rig.client.post(url, json=body, headers=SERVICE)).status_code in (200, 201)
    again = await rig.client.put("/v1/models/chat-model", json={**first, "model": "gpt-4.1"})
    assert again.status_code == 200, again.text
    now = (await rig.client.get(url, headers=SERVICE)).json()["data"][-1]
    assert (now["modelId"], float(now["inputPerMillion"]), float(now["outputPerMillion"])) == ("gpt-4.1", 2.5, 10.0)
