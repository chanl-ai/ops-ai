"""Whom an account reads as signed in, by failure mode: the system's identity URL or an id is shown as the person
(Salesforce's id token `sub`); a system whose read names the person (GitHub's /user `login`) still shows nobody.
Rig: test_sign_in_place's plugin with a fake system."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from .conftest import team_credential
from .test_sign_in_place import APP, admin, signin_client
from .test_sign_in_refused import _account, _complete, _started  # pyright: ignore[reportPrivateUsage]

IDENTITY = "https://login.signin.test/id/00Dbm000000001/005bm000000001"


def _jwt(claims: dict[str, Any]) -> str:
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"e30.{body}.sig"


def system(me: dict[str, Any]) -> httpx.AsyncClient:
    """A system whose token answer carries an id token naming the person only by its identity URL, and whose test
    read answers `me`."""

    async def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "at-1", "id_token": _jwt({"sub": IDENTITY})})
        return httpx.Response(200, json=me)

    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


@pytest.fixture
async def client(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[httpx.AsyncClient]:
    async with signin_client(engine, seed, tenant, catalog_tools, upstream=system({"login": "priya-dev"})) as c:
        yield c


async def _signed_in(client: httpx.AsyncClient, tenant: str) -> str:
    credential = await team_credential(client, admin(tenant), APP, "signin-own", "s3cret-value")
    account = await _account(client, tenant, credentialId=credential)
    state = await _started(client, admin(tenant), account)
    done = await _complete(client, admin(tenant), account, state=state, code="the-code")
    assert done.status_code == 200, done.text
    return account


async def _shown(client: httpx.AsyncClient, tenant: str, account: str) -> Any:
    detail: dict[str, Any] = (await client.get(f"/v1/apps/{APP}/accounts/{account}", headers=admin(tenant))).json()[
        "data"
    ]
    signed: dict[str, Any] = detail.get("signedIn") or {}
    return signed.get("account")


async def test_an_identity_url_is_never_shown_as_who_signed_in(client: httpx.AsyncClient, tenant: str) -> None:
    account = await _signed_in(client, tenant)
    shown = await _shown(client, tenant, account)
    assert shown != IDENTITY and "://" not in str(shown), shown


async def test_the_login_a_test_read_names_is_who_signed_in(client: httpx.AsyncClient, tenant: str) -> None:
    account = await _signed_in(client, tenant)
    tested = await client.post(
        f"/v1/apps/{APP}/accounts/{account}/test", json={"account": "team"}, headers=admin(tenant)
    )
    assert tested.status_code == 200, tested.text
    assert await _shown(client, tenant, account) == "priya-dev"
