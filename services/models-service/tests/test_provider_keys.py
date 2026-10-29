"""An account's model provider keys (owner, 2026-10-27), by failure mode: the provider called without the key an admin
saved, a replaced key that waits out the cache before it is used, a call that reaches the provider with no key at all,
a value readable back or stored in the clear, a key set by someone who is not an account admin, another account's key
used for this one's call, a key deleted while a connection still names it, the dev settings key winning over a saved
one, and a deployment outside dev still starting with keys in its settings."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from fastapi import Header, Request
from pydantic import SecretStr

from ops_identity import Principal
from ops_identity.fastapi import current_principal
from ops_models.__main__ import dev_provider_keys
from ops_models.app import create_models_app
from ops_models.store import provider_keys
from ops_policy import AesGcmCipher
from ops_service_kit.contract import response_checker
from ops_service_kit.settings import Settings

from .conftest import SERVICE, Models

CIPHER = AesGcmCipher("cd" * 32)


def _provider(seen: list[str | None]) -> httpx.AsyncClient:
    """An OpenAI-compatible provider that answers any completion and records the credential it was sent."""

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization"))
        choice = {"index": 0, "message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}
        usage = {"prompt_tokens": 7, "completion_tokens": 3}
        return httpx.Response(200, json={"id": "up", "object": "chat.completion", "choices": [choice], "usage": usage})

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


def _people(tenant: str) -> Any:
    """A person signed in to `tenant` with the role X-Role names in the team X-Team-Id names (admin of team_security
    is the account admin); a request with a bearer token (a service) is resolved as usual."""

    async def as_person(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        x_team_id: Annotated[str | None, Header()] = None,
        x_role: Annotated[str | None, Header()] = None,
    ) -> Principal:
        if authorization:
            return await current_principal(request, authorization=authorization)
        team = x_team_id or "team_security"
        return Principal(
            kind="person",
            sub="usr_nadia",
            email="nadia@harborpine.example",
            name="nadia",
            tenant_id=tenant,
            team_id=team,
            team_ids=[team],
            roles={team: x_role or "admin"},
            scopes=[],
            auth_method="session",
        )

    return as_person


@dataclass
class Rig:
    client: httpx.AsyncClient
    seen: list[str | None]
    tenant: str
    key_name: str
    alias: str
    key_id: str
    secret: str
    models: Models

    async def save(self, value: str, **headers: str) -> httpx.Response:
        return await self.client.put(f"/v1/provider-keys/{self.key_name}", json={"value": value}, headers=headers)

    async def complete(self, tenant: str | None = None) -> httpx.Response:
        return await self.models.complete(self.secret, alias=self.alias, **{"X-Tenant-Id": tenant or self.tenant})


async def _rig(models: Models, in_settings: str | None = None) -> AsyncIterator[Rig]:
    """A connection naming a fresh key, an alias on it and a model key, for a fresh tenant; `in_settings` is the dev
    stack's value for that key from settings."""
    seen: list[str | None] = []
    tenant, key_name = f"t_{uuid4().hex[:8]}", f"OPENAI_{uuid4().hex[:6].upper()}"
    fallback = {key_name: in_settings} if in_settings else {}
    app = create_models_app(models.engine, upstream=_provider(seen), cipher=CIPHER, provider_secrets=fallback)
    app.dependency_overrides[current_principal] = _people(tenant)
    hooks = {"response": [response_checker(app)]}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://models", event_hooks=hooks) as client:
        conn = {"name": f"openai-{uuid4().hex[:8]}", "type": "openai-compatible", "baseUrl": "http://up/v1"}
        pid = await client.post("/v1/models/providers", json={**conn, "keyRef": key_name}, headers=SERVICE)
        alias = f"bank-keys-{uuid4().hex[:8]}"
        version = {"name": alias, "providerId": pid.json()["data"]["id"], "modelId": "gpt-4.1-mini"}
        made = await client.post(
            "/v1/models/aliases", json={**version, "clearedSensitivity": "internal"}, headers=SERVICE
        )
        assert made.status_code == 201, made.text
        on_app = Models(client, models.engine, app)
        key_id, secret = await on_app.key(budget="5")
        yield Rig(client, seen, tenant, key_name, alias, key_id, secret, on_app)


@pytest.fixture
async def rig(models: Models) -> AsyncIterator[Rig]:
    async for r in _rig(models):
        yield r


async def test_a_saved_key_signs_the_call_and_a_replacement_applies_on_the_next_call(rig: Rig) -> None:
    saved = await rig.save("sk-first")
    assert saved.status_code == 200, saved.text
    assert (await rig.complete()).status_code == 200
    replaced = await rig.save("sk-second")
    assert replaced.json()["data"]["version"] == 2 and replaced.json()["data"]["rotatedAt"]
    assert (await rig.complete()).status_code == 200
    assert rig.seen == ["Bearer sk-first", "Bearer sk-second"], "the replacement is used at once, not after a minute"


async def test_a_connection_whose_key_is_not_saved_is_refused_without_calling_the_provider(rig: Rig) -> None:
    r = await rig.complete()
    assert r.status_code == 503, r.text
    assert r.json()["error"]["code"] == "provider_key_missing"
    assert rig.key_name in r.json()["error"]["message"]
    assert rig.seen == []
    assert [c["reason"] for c in await rig.models.calls(rig.key_id)] == ["provider_key_missing"]


async def test_a_value_is_never_read_back_nor_stored_in_the_clear(rig: Rig) -> None:
    saved = await rig.save("sk-do-not-show")
    listed = await rig.client.get("/v1/provider-keys")
    assert "sk-do-not-show" not in saved.text + listed.text
    assert [k["name"] for k in listed.json()["data"]] == [rig.key_name]
    async with rig.models.engine.connect() as c:
        stored = await c.scalar(
            sa.select(provider_keys.c.ciphertext).where(
                provider_keys.c.tenant_id == rig.tenant, provider_keys.c.name == rig.key_name
            )
        )
    assert stored and "sk-do-not-show" not in stored


async def test_only_an_account_admin_sets_lists_or_deletes_a_key(rig: Rig) -> None:
    team_admin = {"X-Team-Id": "team_ops", "X-Role": "admin"}
    builder_of_security = {"X-Team-Id": "team_security", "X-Role": "builder"}
    for who in (team_admin, builder_of_security):
        assert (await rig.save("sk-x", **who)).status_code == 403
        assert (await rig.client.get("/v1/provider-keys", headers=who)).status_code == 403
        assert (await rig.client.delete(f"/v1/provider-keys/{rig.key_name}", headers=who)).status_code == 403
    service = await rig.client.put(f"/v1/provider-keys/{rig.key_name}", json={"value": "sk-x"}, headers=SERVICE)
    assert service.status_code in (401, 403), "a service token is not an account admin"
    assert (await rig.client.get("/v1/provider-keys")).json()["data"] == []


async def test_another_accounts_key_is_not_used_for_this_accounts_call(rig: Rig) -> None:
    assert (await rig.save("sk-mine")).status_code == 200
    r = await rig.complete(tenant=f"t_{uuid4().hex[:8]}")
    assert r.status_code == 503 and rig.seen == []


async def test_a_key_a_connection_names_is_not_deleted(rig: Rig) -> None:
    await rig.save("sk-in-use")
    r = await rig.client.delete(f"/v1/provider-keys/{rig.key_name}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "key_in_use"
    other = f"SPARE_{uuid4().hex[:6].upper()}"
    await rig.client.put(f"/v1/provider-keys/{other}", json={"value": "sk-spare"})
    assert (await rig.client.delete(f"/v1/provider-keys/{other}")).status_code == 204
    assert (await rig.client.delete(f"/v1/provider-keys/{other}")).status_code == 404


async def test_the_dev_settings_key_answers_only_while_the_account_has_none(models: Models) -> None:
    async for rig in _rig(models, in_settings="sk-from-env"):
        assert (await rig.complete()).status_code == 200
        await rig.save("sk-saved")
        assert (await rig.complete()).status_code == 200
        assert rig.seen == ["Bearer sk-from-env", "Bearer sk-saved"]


def test_outside_dev_a_key_in_settings_stops_start_up() -> None:
    # Only the fields start-up reads here; a full production Settings needs platform auth and keys this test has not.
    settings = Settings.model_construct(
        environment="production", model_provider_keys={"OPENAI_API_KEY": SecretStr("sk-env")}
    )
    with pytest.raises(SystemExit, match="OPENAI_API_KEY"):
        dev_provider_keys(settings)
