"""A connection saved with its own base URL (a gateway in front of OpenAI) is where the key check, the model list and
the chat model's calls go, by failure mode: any of the three still reaching api.openai.com with the company's key
instead of the gateway the connection names. The provider and DNS are fakes here."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from ops_identity.fastapi import current_principal
from ops_models.app import create_models_app
from ops_models.connection_settings import OPENAI_LOCAL
from ops_models.store import Providers
from ops_service_kit.contract import response_checker
from ops_service_kit.ids import now_iso
from ops_service_kit.public_address import PublicFetch
from ops_service_kit.settings import Settings

from .conftest import SERVICE, Models
from .test_provider_keys import people

GATEWAY = "https://gateway.example/v1"


@dataclass
class Resolver:
    answer: str = "52.1.2.3"

    async def resolve(self, host: str, port: int) -> list[str]:
        return [self.answer]


@dataclass
class Rig:
    client: httpx.AsyncClient
    seen: list[str] = field(default_factory=list[str])
    models: Models | None = None
    secret: str = ""
    aliases: tuple[str, str] = ("", "")
    tenant: str = ""
    dns: Resolver = field(default_factory=Resolver)


@pytest.fixture
async def rig(models: Models) -> AsyncIterator[Rig]:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        # The key check connects to the checked address and names the host in the header; a call goes by host.
        seen.append(f"{request.headers.get('host') or request.url.host}{request.url.path}")
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "model-a"}]})
        choice = {"index": 0, "message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}
        usage = {"prompt_tokens": 7, "completion_tokens": 3}
        return httpx.Response(200, json={"id": "up", "object": "chat.completion", "choices": [choice], "usage": usage})

    tenant = f"t_{uuid4().hex[:8]}"
    names = (f"chat-{uuid4().hex[:8]}", f"assist-{uuid4().hex[:8]}")
    dns = Resolver()
    app = create_models_app(
        models.engine,
        upstream=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        key_fetch=PublicFetch(resolver=dns, max_redirects=0),
        chat_aliases=names,
    )
    app.dependency_overrides[current_principal] = people(tenant, owner=True)
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://models", event_hooks=hooks
    ) as client:
        assert (await client.put("/v1/provider-keys/MAIN", json={"value": "sk-good"})).status_code == 200
        # The connection chat uses for OpenAI, saved with a gateway's base URL.
        made = await client.post(
            "/v1/models/providers",
            json={"name": f"{names[0]}-openai", "type": "openai-compatible", "baseUrl": GATEWAY, "keyRef": "MAIN"},
            headers=SERVICE,
        )
        assert made.status_code in (200, 201), made.text
        on_app = Models(client, models.engine, app)
        _, secret = await on_app.key(budget="5")
        yield Rig(client, seen, on_app, secret, names, tenant, dns)


async def test_the_key_check_and_the_model_list_reach_the_connections_base_url(rig: Rig) -> None:
    checked = await rig.client.post("/v1/provider-keys/MAIN/check", json={"provider": "openai"})
    assert checked.status_code == 200 and checked.json()["data"]["ok"] is True, checked.text
    listed = await rig.client.get("/v1/provider-keys/MAIN/models", params={"provider": "openai"})
    assert listed.status_code == 200, listed.text
    assert rig.seen == ["gateway.example/v1/models"] * 2


async def test_the_chat_model_call_reaches_the_connections_base_url(rig: Rig) -> None:
    # A catalogued model behind a gateway is priced from the provider's catalogue, as at OpenAI's own address.
    body = {"provider": "openai", "model": "gpt-5.4-mini", "keyName": "MAIN"}
    assert (await rig.client.put("/v1/models/chat-model", json=body)).status_code == 200
    assert rig.models is not None
    answer = await rig.models.complete(rig.secret, alias=rig.aliases[0], **{"X-Tenant-Id": rig.tenant})
    assert answer.status_code == 200, answer.text
    assert rig.seen == ["gateway.example/v1/chat/completions"]


@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "10.0.0.5"])
async def test_a_connection_base_that_resolves_inside_the_network_never_gets_the_key(rig: Rig, address: str) -> None:
    rig.dns.answer = address
    refused = await rig.client.post("/v1/provider-keys/MAIN/check", json={"provider": "openai"})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "endpoint_refused", refused.text
    assert rig.seen == []


async def test_the_installs_own_connection_is_used_when_chat_has_none(
    models: Models, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.headers.get('host')}{request.url.path}")
        return httpx.Response(200, json={"data": [{"id": "model-a"}]})

    app = create_models_app(
        models.engine,
        upstream=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        key_fetch=PublicFetch(resolver=Resolver(), max_redirects=0),
        chat_aliases=(f"chat-{uuid4().hex[:8]}", "assistant"),
    )
    app.dependency_overrides[current_principal] = people(f"t_{uuid4().hex[:8]}", owner=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://models") as client:
        assert (await client.put("/v1/provider-keys/MAIN", json={"value": "sk-good"})).status_code == 200
        await Providers(models.engine).ensure(
            {"id": OPENAI_LOCAL, "name": OPENAI_LOCAL, "type": "openai-compatible", "key_ref": None,
             "base_url": GATEWAY, "created_at": now_iso()}
        )  # fmt: skip
        checked = await client.post("/v1/provider-keys/MAIN/check", json={"provider": "openai"})
        assert checked.status_code == 200, checked.text
    assert seen == ["gateway.example/v1/models"]


async def test_the_dev_fake_is_the_only_local_address_a_key_reaches(
    models: Models, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["host"])
        return httpx.Response(200, json={"data": [{"id": "model-a"}]})

    monkeypatch.setenv("OPS_MODELS_FAKE_OPENAI_URL", "http://127.0.0.1:8746/v1")
    app = create_models_app(models.engine, upstream=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
    app.dependency_overrides[current_principal] = people(f"t_{uuid4().hex[:8]}", owner=True)
    providers = Providers(models.engine)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://models") as client:
        assert (await client.put("/v1/provider-keys/MAIN", json={"value": "sk-good"})).status_code == 200
        for base in ("http://127.0.0.1:8746/v1", "http://127.0.0.1:9999/v1"):
            await providers.ensure({"id": OPENAI_LOCAL, "name": OPENAI_LOCAL, "type": "openai-compatible",
                                    "key_ref": None, "base_url": base, "created_at": now_iso()})  # fmt: skip
            await providers.rebind(
                OPENAI_LOCAL, {"base_url": base, "key_ref": None, "api_version": None, "region": None}
            )
            answer = await client.post("/v1/provider-keys/MAIN/check", json={"provider": "openai"})
            if base.endswith("8746/v1"):
                assert answer.status_code == 200 and answer.json()["data"]["ok"] is True, answer.text
            else:
                assert answer.status_code == 422, answer.text
    assert seen == ["127.0.0.1:8746"]


def test_the_fake_openai_url_is_refused_outside_dev() -> None:
    with pytest.raises(ValueError, match="models_fake_openai_url"):
        Settings(
            environment="production",
            auth_mode="platform",
            credential_store="sealed",
            review_key=SecretStr("r" * 40),
            models_fake_openai_url="http://127.0.0.1:8746/v1",
        )
