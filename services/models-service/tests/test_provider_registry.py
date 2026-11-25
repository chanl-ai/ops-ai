"""Provider types come from the registry, by failure mode: an entry naming an adapter no code registers is served
anyway (it must stop start-up); an entry added only as a JSON file in the extra folder is missing from the add list; a
connection's secrets come back in a reply; and a key the provider refuses on a registry type's model list reads as
working. The provider and DNS are fakes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest

from ops_identity.fastapi import current_principal, current_tenant_caller
from ops_models.app import create_models_app
from ops_models.registry import RegistryInvalid
from ops_service_kit.contract import response_checker
from ops_service_kit.public_address import PublicFetch

from .conftest import Models
from .test_provider_key_check import Resolver
from .test_provider_keys import people

FAKE: dict[str, Any] = {
    "id": "acme-llm",
    "label": "Acme LLM",
    "icon": "acme",
    "adapter": "openai-compatible",
    "baseUrl": "https://llm.acme.example/v1",
    "connection": {
        "type": "object",
        "properties": {"apiKey": {"type": "string", "title": "API key", "x-secret": True}},
        "required": ["apiKey"],
    },
    "modelList": {"path": "/models", "auth": "bearer"},
}


def _extra(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, entry: dict[str, Any]) -> None:
    (tmp_path / f"{entry['id']}.json").write_text(json.dumps(entry))
    monkeypatch.setenv("OPS_MODELS_PROVIDER_REGISTRY_EXTRA", str(tmp_path))


def _client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)  # pyright: ignore[reportArgumentType]
    hooks = {"response": [response_checker(app)]}  # pyright: ignore[reportArgumentType]
    return httpx.AsyncClient(transport=transport, base_url="http://models", event_hooks=hooks)


def test_an_entry_naming_an_unknown_adapter_stops_start_up(
    models: Models, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _extra(tmp_path, monkeypatch, {**FAKE, "adapter": "acme-sdk"})
    with pytest.raises(RegistryInvalid, match="acme-sdk"):
        create_models_app(models.engine)


async def test_an_entry_added_as_json_alone_is_in_the_add_list(
    models: Models, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _extra(tmp_path, monkeypatch, FAKE)
    app = create_models_app(models.engine)
    person = people(f"t_{uuid4().hex[:8]}")
    app.dependency_overrides[current_principal] = app.dependency_overrides[current_tenant_caller] = person
    async with _client(app) as c:
        listed = (await c.get("/v1/models/provider-types")).json()["data"]
        member = await c.get("/v1/models/provider-types", headers={"X-Role": "member"})
    assert member.status_code == 403, "a member who is not an account admin reads no provider types"
    ids = [t["id"] for t in listed]
    assert "acme-llm" in ids and {"openai", "anthropic", "google", "azure-openai", "bedrock"} <= set(ids), ids
    acme = next(t for t in listed if t["id"] == "acme-llm")
    assert acme["connection"]["properties"]["apiKey"]["x-secret"] is True and acme["listsModels"], acme


async def test_a_connection_secret_is_never_returned(models: Models) -> None:
    seen: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"modelSummaries": [{"modelId": "anthropic.claude-sonnet-4-6"}]})

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    app = create_models_app(models.engine, upstream=upstream, key_fetch=PublicFetch(resolver=Resolver()))
    # One account admin for the connection routes and the key routes alike.
    person = people(f"t_{uuid4().hex[:8]}")
    app.dependency_overrides[current_principal] = app.dependency_overrides[current_tenant_caller] = person
    secret = "wJalrXUtnFEMI-K7MDENG-bPxRfiCYEXAMPLEKEY"
    async with _client(app) as c:
        body = {
            "name": f"bedrock-{uuid4().hex[:6]}",
            "type": "bedrock",
            "region": "us-east-1",
            "keyRef": "BEDROCK_MAIN",
            "secrets": {"accessKeyId": "AKIAEXAMPLE", "secretAccessKey": secret},
        }
        made = await c.post("/v1/models/providers", json=body)
        check = await c.post(
            "/v1/provider-keys/BEDROCK_MAIN/check", json={"provider": "bedrock", "region": "us-east-1"}
        )
        replies = [made, check, await c.get("/v1/models/providers"), await c.get("/v1/provider-keys")]
        replies.append(await c.get("/v1/models/provider-types"))
    assert made.status_code == 201, made.text
    assert check.status_code == 200, check.text
    assert check.json()["data"] == {"ok": True, "reason": None, "models": 1}, check.text
    assert all(secret not in r.text and secret[:12] not in r.text for r in replies), [r.text[:200] for r in replies]
    signed = seen[0].headers["authorization"]
    assert seen[0].headers["host"] == "bedrock.us-east-1.amazonaws.com" and "Credential=AKIAEXAMPLE/" in signed, signed
    assert secret not in signed, signed


async def test_a_key_a_registry_type_refuses_reads_as_refused(models: Models) -> None:
    seen: list[httpx.Request] = []

    def provider(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(401, json={"error": {"message": "invalid x-api-key sk-ant-wr****"}})

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(provider))
    app = create_models_app(models.engine, upstream=upstream, key_fetch=PublicFetch(resolver=Resolver()))
    app.dependency_overrides[current_principal] = people(f"t_{uuid4().hex[:8]}")
    async with _client(app) as c:
        assert (await c.put("/v1/provider-keys/ANTHROPIC", json={"value": "sk-ant-wrong"})).status_code == 200
        check = await c.post("/v1/provider-keys/ANTHROPIC/check", json={"provider": "anthropic"})
        aimed = {"provider": "openai", "endpoint": "https://collector.example/v1"}
        await c.post("/v1/provider-keys/ANTHROPIC/check", json=aimed)
    assert check.json()["data"] == {"ok": False, "reason": "The provider refused the key.", "models": 0}, check.text
    sent = seen[0]
    asked = (sent.headers["host"], sent.url.path, sent.headers["x-api-key"])
    assert asked == ("api.anthropic.com", "/v1/models", "sk-ant-wrong"), asked
    assert "sk-ant-wr" not in check.text, check.text
    assert seen[1].headers["host"] == "api.openai.com", "an OpenAI key goes only to OpenAI's own address"
