"""An app credential's client secret given after the credential was made, by failure mode: the secret is stored but
the credential never names it, so the token exchange sends none and the system refuses it as wrong; and a credential
that holds no secret at all is reported as having a wrong one, sending the admin to replace a secret that
is not there."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from .test_sign_in_place import APP, admin, signin_client
from .test_sign_in_refused import _account, _complete, _started  # pyright: ignore[reportPrivateUsage]

SECRET = "given-later-5c1e"


class System:
    """The system's token address: a code exchanged with the right client secret gets a token, anything else GitHub's
    refusal of a wrong one."""

    def __init__(self) -> None:
        self.sent: list[str | None] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/token"):
            return httpx.Response(200, json={"id": "me"})
        secret = dict(parse_qsl(request.content.decode())).get("client_secret")
        self.sent.append(secret)
        if secret != SECRET:
            return httpx.Response(200, json={"error": "incorrect_client_credentials"})
        return httpx.Response(200, json={"access_token": "at-1", "token_type": "bearer", "expires_in": 3600})


@pytest.fixture
def system() -> System:
    return System()


@pytest.fixture
async def client(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]], system: System
) -> AsyncIterator[httpx.AsyncClient]:
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(system.handle))
    async with signin_client(engine, seed, tenant, catalog_tools, upstream=upstream) as c:
        yield c


async def _credential(client: httpx.AsyncClient, tenant: str) -> str:
    """A credential made with no secret, as the New app credential window allows."""
    body = {"app": APP, "name": "Signin prod", "clientId": "signin-own"}
    made = await client.post("/v1/app-credentials", json=body, headers=admin(tenant))
    assert made.status_code == 201, made.text
    return str(made.json()["data"]["id"])


async def test_a_credential_given_its_secret_after_creation_signs_in_with_it(
    client: httpx.AsyncClient, tenant: str, system: System
) -> None:
    credential = await _credential(client, tenant)
    put = await client.put(
        f"/v1/app-credentials/{credential}/secret", json={"clientSecret": SECRET}, headers=admin(tenant)
    )
    assert put.status_code == 200, put.text
    account = await _account(client, tenant, credentialId=credential)
    state = await _started(client, admin(tenant), account)
    done = await _complete(client, admin(tenant), account, state=state, code="the-code")
    assert system.sent == [SECRET], system.sent
    assert done.status_code == 200, done.text


async def test_a_credential_with_no_secret_says_so_rather_than_wrong(
    client: httpx.AsyncClient, tenant: str, system: System
) -> None:
    account = await _account(client, tenant, credentialId=await _credential(client, tenant))
    state = await _started(client, admin(tenant), account)
    refused = await _complete(client, admin(tenant), account, state=state, code="the-code")
    assert system.sent == [None], system.sent
    details = refused.json()["error"]["details"]
    assert details == {
        "message": "Signin prod has no client secret yet. Add it on its Credentials page.",
        "who": "admin",
        "providerCode": "incorrect_client_credentials",
    }, refused.text
