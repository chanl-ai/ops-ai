"""Signing in twice as the same person at the system, by failure mode: a second account of the app is kept for an
identity the person already linked, so their calls ask which of two identical accounts to use; the answer does not say
they were already connected; and an account holding someone else's sign-in is removed with the duplicate."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from .conftest import team_credential
from .test_review_decisions import person
from .test_sign_in_place import APP, TEAM, admin, signin_client
from .test_sign_in_refused import _account, _complete, _started  # pyright: ignore[reportPrivateUsage]

JAMES = "James Richardson"


LOGINS = ["harbor-ops"]


def as_user(login: str) -> httpx.AsyncClient:
    """A system whose sign-in names, in its id token, the login at the head of LOGINS (`login` to start with)."""
    LOGINS[:] = [login]

    async def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            body = base64.urlsafe_b64encode(json.dumps({"preferred_username": LOGINS[0]}).encode()).decode().rstrip("=")
            token = {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600, "id_token": f"e30.{body}.s"}
            return httpx.Response(200, json=token)
        return httpx.Response(200, json={"id": "me"})

    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


@pytest.fixture
async def client(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[httpx.AsyncClient]:
    async with signin_client(engine, seed, tenant, catalog_tools, upstream=as_user("harbor-ops")) as c:
        yield c


async def _own_sign_in(client: httpx.AsyncClient, tenant: str, account: str) -> httpx.Response:
    james = person(tenant, JAMES, {TEAM: "builder"})
    state = await _started(client, james, account, own=True)
    return await _complete(client, james, account, state=state, code="the-code")


async def test_the_same_identity_signed_in_twice_keeps_one_account(client: httpx.AsyncClient, tenant: str) -> None:
    credential = await team_credential(client, admin(tenant), APP, "signin-own", "s3cret-value")
    first = await _account(client, tenant, credentialId=credential, signIn="person")
    body = {"name": "Signin desk · second account", "credentialId": credential, "signIn": "person"}
    made = await client.post(f"/v1/apps/{APP}/accounts", json=body, headers=admin(tenant))
    assert made.status_code == 201, made.text
    second = str(made.json()["data"]["id"])

    assert (await _own_sign_in(client, tenant, first)).status_code == 200
    again = await _own_sign_in(client, tenant, second)
    assert again.status_code == 200, again.text
    done = again.json()["data"]
    assert done["accountId"] == first and done["alreadyConnectedAs"] == "harbor-ops", done

    james = person(tenant, JAMES, {TEAM: "builder"})
    rows = [r for r in (await client.get("/v1/me/connections", headers=james)).json()["data"] if r["appId"] == APP]
    assert len(rows) == 1 and rows[0]["accountCount"] == 1, rows
    page = (await client.get(f"/v1/apps/{APP}", headers=admin(tenant))).json()["data"]
    assert second not in {a["id"] for a in page["accounts"]}, "the account made only for the duplicate is gone"


async def _another(client: httpx.AsyncClient, tenant: str, account: str) -> httpx.Response:
    """Add another account from Connectors: the sign-in starts on a new account of the same auth config."""
    james = person(tenant, JAMES, {TEAM: "builder"})
    started = await client.post(f"/v1/me/accounts/{account}/another", headers=james)
    assert started.status_code == 200, started.text
    from urllib.parse import parse_qs, urlsplit  # noqa: PLC0415

    state = parse_qs(urlsplit(str(started.json()["data"]["authorizeUrl"])).query)["state"][0]
    return await _complete(client, james, account, state=state, code="the-code")


async def _james_rows(client: httpx.AsyncClient, tenant: str) -> list[dict[str, Any]]:
    james = person(tenant, JAMES, {TEAM: "builder"})
    return [r for r in (await client.get("/v1/me/connections", headers=james)).json()["data"] if r["appId"] == APP]


async def test_another_account_as_a_different_login_is_a_second_account_on_the_same_config(
    client: httpx.AsyncClient, tenant: str
) -> None:
    credential = await team_credential(client, admin(tenant), APP, "signin-own", "s3cret-value")
    first = await _account(client, tenant, credentialId=credential, signIn="person")
    assert (await _own_sign_in(client, tenant, first)).status_code == 200
    LOGINS[:] = ["harbor-office"]
    done = await _another(client, tenant, first)
    assert done.status_code == 200, done.text
    assert done.json()["data"]["accountId"] != first and not done.json()["data"].get("alreadyConnectedAs")
    rows = await _james_rows(client, tenant)
    assert len(rows) == 1 and rows[0]["accountCount"] == 2, rows
    assert {a["account"] for a in rows[0]["accounts"]} == {"harbor-ops", "harbor-office"}, rows
    page = (await client.get(f"/v1/apps/{APP}", headers=admin(tenant))).json()["data"]
    configs = {a["id"]: a.get("configId") for a in page["accounts"] if a["kind"] == "team"}
    assert len(set(configs.values())) == 1, configs
    # Someone else in the team is not offered James's own second account.
    maya = person(tenant, "Maya Okafor", {TEAM: "approver"})
    theirs = [
        r for r in (await client.get("/v1/me/accounts?every=true", headers=maya)).json()["data"] if r["appId"] == APP
    ]
    assert [r["connectionId"] for r in theirs] == [first], theirs


async def test_another_account_as_the_same_login_updates_the_first(client: httpx.AsyncClient, tenant: str) -> None:
    credential = await team_credential(client, admin(tenant), APP, "signin-own", "s3cret-value")
    first = await _account(client, tenant, credentialId=credential, signIn="person")
    assert (await _own_sign_in(client, tenant, first)).status_code == 200
    done = (await _another(client, tenant, first)).json()["data"]
    assert done["accountId"] == first and done["alreadyConnectedAs"] == "harbor-ops", done
    rows = await _james_rows(client, tenant)
    assert rows[0]["accountCount"] == 1 and len(rows[0]["accounts"]) == 1, rows
