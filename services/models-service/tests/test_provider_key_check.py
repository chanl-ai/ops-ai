"""Testing a saved model key and listing what it reaches, by failure mode: the provider asked with the wrong header or
place for its kind (OpenAI, Azure OpenAI, Anthropic); a key the provider refuses read as working, or the provider's
own answer passed back; the key sent to a host that is not the provider, to a private address, or along a redirect;
and someone who is not an account admin testing a key. The provider and DNS are fakes here."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from uuid import uuid4

import httpx
import pytest

from ops_identity.fastapi import current_principal
from ops_models.app import create_models_app
from ops_service_kit.contract import response_checker
from ops_service_kit.public_address import PublicFetch

from .conftest import Models
from .test_provider_keys import _people

GOOD = "sk-good"
AZURE = "https://contoso.openai.azure.com"


@dataclass
class Resolver:
    """DNS: every name is a public address unless listed."""

    answers: dict[str, str] = field(default_factory=dict)

    async def resolve(self, host: str, port: int) -> list[str]:
        return [self.answers.get(host, "52.1.2.3")]


@dataclass
class Rig:
    client: httpx.AsyncClient
    seen: list[tuple[str, str]]
    dns: Resolver
    redirect: list[str]


def _upstream(seen: list[tuple[str, str]], redirect: list[str]) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        sent = (
            request.headers.get("authorization") or request.headers.get("api-key") or request.headers.get("x-api-key")
        )
        seen.append((f"{request.headers['host']}{request.url.raw_path.decode()}", sent or ""))
        if redirect:
            return httpx.Response(302, headers={"location": redirect[0]})
        if (sent or "").removeprefix("Bearer ") != GOOD:
            return httpx.Response(401, json={"error": {"message": "Incorrect API key provided: sk-wr****"}})
        if request.url.path == "/openai/deployments":
            return httpx.Response(200, json={"data": [{"id": "chat-prod", "model": "gpt-4o"}]})
        return httpx.Response(200, json={"data": [{"id": "model-a"}, {"id": "model-b"}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


@pytest.fixture
async def rig(models: Models) -> AsyncIterator[Rig]:
    seen: list[tuple[str, str]] = []
    redirect: list[str] = []
    dns = Resolver()
    app = create_models_app(
        models.engine, upstream=_upstream(seen, redirect), key_fetch=PublicFetch(resolver=dns, max_redirects=0)
    )
    app.dependency_overrides[current_principal] = _people(f"t_{uuid4().hex[:8]}")
    transport = httpx.ASGITransport(app=app)
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(transport=transport, base_url="http://models", event_hooks=hooks) as client:
        assert (await client.put("/v1/provider-keys/MAIN", json={"value": GOOD})).status_code == 200
        yield Rig(client, seen, dns, redirect)


@pytest.mark.parametrize(
    ("body", "sent_to", "header", "expected"),
    [
        ({"provider": "openai"}, "api.openai.com/v1/models", f"Bearer {GOOD}", ["model-a", "model-b"]),
        (
            {"provider": "azure-openai", "endpoint": AZURE, "apiVersion": "2022-12-01"},
            "contoso.openai.azure.com/openai/deployments?api-version=2022-12-01",
            GOOD,
            ["chat-prod"],
        ),
        ({"provider": "anthropic"}, "api.anthropic.com/v1/models", GOOD, ["model-a", "model-b"]),
    ],
)
async def test_a_saved_key_is_tested_and_lists_its_models_where_its_provider_keeps_them(
    rig: Rig, body: dict[str, str], sent_to: str, header: str, expected: list[str]
) -> None:
    checked = await rig.client.post("/v1/provider-keys/MAIN/check", json=body)
    assert checked.status_code == 200, checked.text
    assert checked.json()["data"]["ok"] is True
    listed = await rig.client.get("/v1/provider-keys/MAIN/models", params=body)
    assert listed.status_code == 200, listed.text
    assert [m["id"] for m in listed.json()["data"]] == expected
    assert rig.seen[-1] == (sent_to, header)


async def test_a_key_the_provider_refuses_reads_as_refused_without_the_providers_words(rig: Rig) -> None:
    await rig.client.put("/v1/provider-keys/MAIN", json={"value": "sk-wrong"})
    checked = await rig.client.post("/v1/provider-keys/MAIN/check", json={"provider": "openai"})
    assert checked.status_code == 200, checked.text
    assert checked.json()["data"] | {} == {"ok": False, "reason": "The provider refused the key.", "models": 0}
    listed = await rig.client.get("/v1/provider-keys/MAIN/models", params={"provider": "openai"})
    assert listed.status_code == 422 and listed.json()["error"]["code"] == "key_refused", listed.text
    assert "sk-wr" not in listed.text


@pytest.mark.parametrize(
    "endpoint",
    ["https://evil.example", "https://contoso.openai.azure.com.evil.example", "https://u:p@contoso.openai.azure.com",
     "https://contoso.openai.azure.com:8443", "https://10.0.0.5", "http://contoso.openai.azure.com"],
)  # fmt: skip
async def test_the_key_never_goes_to_a_host_that_is_not_an_azure_resource(rig: Rig, endpoint: str) -> None:
    body = {"provider": "azure-openai", "endpoint": endpoint}
    refused = await rig.client.post("/v1/provider-keys/MAIN/check", json=body)
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "endpoint_refused", refused.text
    assert rig.seen == []


async def test_the_key_never_goes_to_a_private_address(rig: Rig) -> None:
    rig.dns.answers["contoso.openai.azure.com"] = "10.0.0.5"
    refused = await rig.client.post(
        "/v1/provider-keys/MAIN/check", json={"provider": "azure-openai", "endpoint": AZURE}
    )
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "endpoint_refused", refused.text
    assert rig.seen == []


async def test_a_redirect_is_not_followed_with_the_key(rig: Rig) -> None:
    rig.redirect.append("http://169.254.169.254/latest/meta-data/")
    checked = await rig.client.post("/v1/provider-keys/MAIN/check", json={"provider": "openai"})
    assert checked.json()["data"]["ok"] is False, checked.text
    assert [s[0] for s in rig.seen] == ["api.openai.com/v1/models"]


async def test_only_an_account_admin_tests_a_key(rig: Rig) -> None:
    member = {"X-Team-Id": "team_ops", "X-Role": "viewer"}
    refused = await rig.client.post("/v1/provider-keys/MAIN/check", json={"provider": "openai"}, headers=member)
    assert refused.status_code == 403, refused.text
