"""Choosing the chat model on first run, by failure mode: the chat aliases left on the old model or never created on a
fresh install; a call that goes to the wrong place or with the wrong header for its provider (Anthropic through its
OpenAI-compatible endpoint); a second choice adding a second connection instead of moving the first; someone who is
not an account admin, or a key not saved, changing what chat uses; an Azure endpoint outside openai.azure.com; and a
fresh chat alias priced at zero, which lets every budget pass."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest

from ops_identity.fastapi import current_principal
from ops_models.app import create_models_app
from ops_models.catalog import Catalog
from ops_models.store.aliases import Aliases, AliasFields
from ops_service_kit.contract import response_checker

from .conftest import SERVICE, Models
from .test_provider_keys import people

AZURE = "https://contoso.openai.azure.com"
# An Azure deployment name is the customer's own, so the catalog never prices it: the admin gives the price.
PRICE = {"inputPerMillion": "2", "outputPerMillion": "8"}


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
    # The install's first admin chooses the chat model: an account admin who is also the workspace's Owner.
    app.dependency_overrides[current_principal] = people(tenant, owner=True)
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
        ({"provider": "openai", "model": "gpt-5.4-mini"}, "api.openai.com/v1/chat/completions", "Bearer sk-good",
         "gpt-5.4-mini"),
        ({"provider": "anthropic", "model": "claude-sonnet-5"}, "api.anthropic.com/v1/chat/completions",
         "Bearer sk-good", "claude-sonnet-5"),
        ({"provider": "azure-openai", "model": "chat-prod", "endpoint": AZURE, "apiVersion": "v1", **PRICE},
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
    first = {"provider": "openai", "model": "gpt-5.4-mini", "keyName": "MAIN"}
    assert (await rig.client.put("/v1/models/chat-model", json=first)).status_code == 200
    again = await rig.client.put("/v1/models/chat-model", json={**first, "model": "gpt-5.4"})
    assert again.status_code == 200, again.text
    assert (await rig.complete(rig.aliases[0])).status_code == 200
    assert rig.seen[-1][2] == "gpt-5.4"
    versions = await rig.client.get(f"/v1/models/aliases/{rig.aliases[0]}/versions", headers=SERVICE)
    assert [v["version"] for v in versions.json()["data"]["data"]] == [1, 2]
    assert len({v["providerId"] for v in versions.json()["data"]["data"]}) == 1


async def test_only_an_account_admin_with_a_saved_key_sets_the_chat_model(rig: Rig) -> None:
    body = {"provider": "openai", "model": "gpt-5.4-mini", "keyName": "MAIN"}
    member = {"X-Team-Id": "team_ops", "X-Role": "viewer"}
    assert (await rig.client.put("/v1/models/chat-model", json=body, headers=member)).status_code == 403
    missing = await rig.client.put("/v1/models/chat-model", json={**body, "keyName": "NOT_SAVED"})
    assert missing.status_code == 404, missing.text
    assert (await rig.client.get(f"/v1/models/aliases/{rig.aliases[0]}/versions", headers=SERVICE)).status_code == 404


async def test_an_azure_endpoint_outside_openai_azure_com_is_refused(rig: Rig) -> None:
    body = {"provider": "azure-openai", "model": "m", "keyName": "MAIN", "endpoint": "https://evil.example"}
    refused = await rig.client.put("/v1/models/chat-model", json={**body, "apiVersion": "v1"})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "endpoint_refused", refused.text


async def test_the_same_model_keeps_the_admins_price_and_a_new_model_takes_its_catalog_price(rig: Rig) -> None:
    first = {"provider": "openai", "model": "gpt-4.1-mini", "keyName": "MAIN"}
    assert (await rig.client.put("/v1/models/chat-model", json=first)).status_code == 200
    url = f"/v1/models/aliases/{rig.aliases[0]}/versions"
    held = (await rig.client.get(url, headers=SERVICE)).json()["data"]["data"][-1]
    # A negotiated rate the admin set on the Models page, on the connection chat-model made: no price is needed there
    # for a catalogued model, as that connection calls OpenAI's own endpoint.
    body = {"providerId": held["providerId"], "modelId": "gpt-4.1-mini", "clearedSensitivity": "confidential"}
    assert (await rig.client.post(url, json=body, headers=SERVICE)).status_code == 201
    rate = {"inputPerMillion": "2.5", "outputPerMillion": "10"}
    assert (await rig.client.post(url, json={**body, **rate}, headers=SERVICE)).status_code == 201

    async def now() -> tuple[str, float, float]:
        v = (await rig.client.get(url, headers=SERVICE)).json()["data"]["data"][-1]
        return v["modelId"], float(v["inputPerMillion"]), float(v["outputPerMillion"])

    assert (await rig.client.put("/v1/models/chat-model", json=first)).status_code == 200
    assert await now() == ("gpt-4.1-mini", 2.5, 10.0)
    moved = await rig.client.put("/v1/models/chat-model", json={**first, "model": "gpt-5.4"})
    assert moved.status_code == 200, moved.text
    listed = Catalog.load().model("openai", "gpt-5.4")
    assert listed is not None
    assert await now() == ("gpt-5.4", listed.input_per_million, listed.output_per_million)


async def test_a_fresh_chat_alias_is_priced_and_an_unpriced_model_is_refused(rig: Rig) -> None:
    unknown = {"provider": "openai", "model": "house-model-7", "keyName": "MAIN"}
    refused = await rig.client.put("/v1/models/chat-model", json=unknown)
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "price_required", refused.text
    assert (await rig.client.get(f"/v1/models/aliases/{rig.aliases[0]}/versions", headers=SERVICE)).status_code == 404
    # gpt-4.1-mini is deprecated on models.dev and still served: the catalog keeps it so a first run can pick it.
    known = {"provider": "openai", "model": "gpt-4.1-mini", "keyName": "MAIN"}
    assert (await rig.client.put("/v1/models/chat-model", json=known)).status_code == 200
    for alias in rig.aliases:
        now = (await rig.client.get(f"/v1/models/aliases/{alias}/versions", headers=SERVICE)).json()["data"]["data"][-1]
        listed = Catalog.load().model("openai", "gpt-4.1-mini")
        assert listed is not None
        assert (float(now["inputPerMillion"]), float(now["outputPerMillion"])) == (
            listed.input_per_million,
            listed.output_per_million,
        ), now


async def test_a_lone_or_zero_chat_price_is_refused_before_anything_is_written(rig: Rig) -> None:
    body = {"provider": "openai", "model": "house-model-7", "keyName": "MAIN"}
    for price, code in [
        ({"inputPerMillion": "2"}, "price_incomplete"),
        ({"inputPerMillion": "0", "outputPerMillion": "0"}, "price_required"),
    ]:
        refused = await rig.client.put("/v1/models/chat-model", json={**body, **price})
        assert refused.status_code == 422 and refused.json()["error"]["code"] == code, refused.text
    # Zero for a model the catalog prices is refused for being zero, not for a missing catalog price.
    zero = {**body, "model": "gpt-5.4", "inputPerMillion": "0", "outputPerMillion": "0"}
    said = (await rig.client.put("/v1/models/chat-model", json=zero)).json()["error"]["message"]
    assert "zero" in said and "no price in the model catalog" not in said, said
    assert (await rig.client.get(f"/v1/models/aliases/{rig.aliases[0]}/versions", headers=SERVICE)).status_code == 404
    connections = await rig.client.get(
        "/v1/models/providers", params={"search": f"{rig.aliases[0]}-openai"}, headers=SERVICE
    )
    assert connections.status_code == 200 and connections.json()["data"]["data"] == [], connections.text


async def test_a_zero_priced_chat_alias_takes_the_given_price_or_is_refused(rig: Rig) -> None:
    # A version written at zero before prices were required: the next choice prices it or is refused.
    for alias in rig.aliases:
        zero = Decimal(0)
        fields: AliasFields = {
            "provider_id": "prov_scripted", "model_id": "old", "cleared_sensitivity": "confidential",
            "input_per_million": zero, "output_per_million": zero, "reasoning_effort": None, "images": False,
        }  # fmt: skip
        assert await Aliases(rig.models.engine).create(alias, "chat", fields)
    body = {"provider": "openai", "model": "house-model-7", "keyName": "MAIN"}
    refused = await rig.client.put("/v1/models/chat-model", json=body)
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "price_required", refused.text
    saved = await rig.client.put(
        "/v1/models/chat-model", json={**body, "inputPerMillion": "2", "outputPerMillion": "8"}
    )
    assert saved.status_code == 200, saved.text
    for alias in rig.aliases:
        now = (await rig.client.get(f"/v1/models/aliases/{alias}/versions", headers=SERVICE)).json()["data"]["data"][-1]
        assert (now["modelId"], float(now["inputPerMillion"]), float(now["outputPerMillion"])) == (
            "house-model-7",
            2,
            8,
        )


async def test_a_body_price_replaces_the_price_a_same_model_alias_holds(rig: Rig) -> None:
    first = {"provider": "openai", "model": "gpt-4.1-mini", "keyName": "MAIN"}
    assert (await rig.client.put("/v1/models/chat-model", json=first)).status_code == 200
    rate = {"inputPerMillion": "2.5", "outputPerMillion": "10"}
    assert (await rig.client.put("/v1/models/chat-model", json={**first, **rate})).status_code == 200
    url = f"/v1/models/aliases/{rig.aliases[0]}/versions"
    held = (await rig.client.get(url, headers=SERVICE)).json()["data"]["data"][-1]
    priced = (held["modelId"], float(held["inputPerMillion"]), float(held["outputPerMillion"]))
    assert priced == ("gpt-4.1-mini", 2.5, 10.0)
