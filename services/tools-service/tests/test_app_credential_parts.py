"""An app credential's parts as its pages show and change them, through the real routes, by failure mode: the
permissions the app's answer offers are refused when a credential is made with them (the window offered labels, the
service takes ids); nothing shows which client secret a credential holds, or a short one is shown nearly whole; and a
credential with accounts on it is deleted from under them, or cannot be deleted at all, rather than offering to move
them to another credential or to Ops AI's app."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from .conftest import team_credential
from .test_app_credential_edit import granting
from .test_sign_in_place import APP, admin, signin_client
from .test_sign_in_refused import _account  # pyright: ignore[reportPrivateUsage]


@pytest.fixture
async def client(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[httpx.AsyncClient]:
    async with signin_client(engine, seed, tenant, catalog_tools, upstream=granting()) as c:
        yield c


async def test_the_permissions_the_app_offers_make_a_credential(client: httpx.AsyncClient, tenant: str) -> None:
    card = (await client.get(f"/v1/apps/{APP}", headers=admin(tenant))).json()["data"]["card"]
    offered = card["plugin"]["scopes"]
    assert offered == [
        {"id": "api", "label": "Read records", "required": True},
        {"id": "write", "label": "Change records", "required": False},
    ], offered
    body = {"app": APP, "clientId": "signin-own", "clientSecret": "s3cret-value", "scopes": [s["id"] for s in offered]}
    made = await client.post("/v1/app-credentials", json=body, headers=admin(tenant))
    assert made.status_code == 201, made.text
    assert made.json()["data"]["permissions"] == offered, made.text


async def test_a_credential_shows_which_secret_it_holds_and_no_more(client: httpx.AsyncClient, tenant: str) -> None:
    made = await team_credential(client, admin(tenant), APP, "signin-own", "first-secret-7c2a")
    page = (await client.get(f"/v1/app-credentials/{made}", headers=admin(tenant))).json()["data"]
    assert (page["secretEnds"], page["holdsSecret"]) == ("7c2a", True), page
    await client.put(f"/v1/app-credentials/{made}/secret", json={"clientSecret": "second-9f1b"}, headers=admin(tenant))
    listed = (await client.get("/v1/app-credentials", headers=admin(tenant))).json()["data"]
    assert next(c for c in listed if c["id"] == made)["secretEnds"] == "9f1b", listed
    short = await team_credential(client, admin(tenant), APP, "signin-short", "abc12")
    page = (await client.get(f"/v1/app-credentials/{short}", headers=admin(tenant))).json()["data"]
    assert (page["secretEnds"], page["holdsSecret"]) == (None, True), page
    assert "abc12" not in str(page)


async def test_a_credential_in_use_names_its_accounts_and_moves_them_when_asked(
    client: httpx.AsyncClient, tenant: str
) -> None:
    old = await team_credential(client, admin(tenant), APP, "signin-old", "old-secret-1111", name="Signin old")
    new = await team_credential(client, admin(tenant), APP, "signin-new", "new-secret-2222", name="Signin new")
    account = await _account(client, tenant, credentialId=old)
    refused = await client.delete(f"/v1/app-credentials/{old}", headers=admin(tenant))
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "credential_in_use", refused.text
    assert [a["id"] for a in refused.json()["error"]["details"]["accounts"]] == [account], refused.text
    moved = await client.delete(f"/v1/app-credentials/{old}?move=true&moveTo={new}", headers=admin(tenant))
    assert moved.status_code == 200 and moved.json()["data"]["moved"] == 1, moved.text
    detail = (await client.get(f"/v1/apps/{APP}/accounts/{account}", headers=admin(tenant))).json()["data"]
    assert detail["credentialId"] == new and detail["status"] == "needs_reconnect", detail
    gone = await client.get(f"/v1/app-credentials/{old}", headers=admin(tenant))
    assert gone.status_code == 404, gone.text


async def test_a_credentials_accounts_move_to_ops_ais_app(client: httpx.AsyncClient, tenant: str) -> None:
    own = await team_credential(client, admin(tenant), APP, "signin-own", "own-secret-3333")
    account = await _account(client, tenant, credentialId=own)
    moved = await client.delete(f"/v1/app-credentials/{own}?move=true", headers=admin(tenant))
    assert moved.status_code == 200, moved.text
    detail = (await client.get(f"/v1/apps/{APP}/accounts/{account}", headers=admin(tenant))).json()["data"]
    assert detail["credentialId"] is None and detail["platformApp"] == "test.signin", detail
