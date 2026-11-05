"""An app credential holds the app registration and is edited in place, through the real routes, by failure mode: a
new client id leaves its accounts reading connected on sign-ins issued to the old one, and the answer does not say how
many must sign in again; a rename alone throws every sign-in away; anyone but a team admin edits it; it takes a
setting its app does not keep on a registration, or edits Ops AI's app; an account signing in with it reads the
registration's setting from itself rather than the credential; and its page cannot say what it holds or may hold."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from .conftest import team_credential
from .test_review_decisions import person
from .test_sign_in_place import APP, TEAM, admin, signin_client
from .test_sign_in_refused import _account, _complete, _started  # pyright: ignore[reportPrivateUsage]


def granting() -> httpx.AsyncClient:
    """A system that grants every code a token."""

    async def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600})
        return httpx.Response(200, json={"id": "me"})

    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


@pytest.fixture
async def client(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[httpx.AsyncClient]:
    async with signin_client(engine, seed, tenant, catalog_tools, upstream=granting()) as c:
        yield c


async def _signed_in(client: httpx.AsyncClient, tenant: str, **credential: Any) -> tuple[str, str]:
    """The team's account on its own credential, signed in as the team; (credential, account)."""
    made = await team_credential(client, admin(tenant), APP, "signin-own", "s3cret", name="Signin prod", **credential)
    account = await _account(client, tenant, credentialId=made)
    state = await _started(client, admin(tenant), account)
    done = await _complete(client, admin(tenant), account, state=state, code="the-code")
    assert done.status_code == 200, done.text
    return made, account


async def _row(client: httpx.AsyncClient, tenant: str, account: str) -> dict[str, Any]:
    page = (await client.get(f"/v1/apps/{APP}", headers=admin(tenant))).json()["data"]
    return next(a for c in page["authConfigs"] for a in c["accounts"] if a["id"] == account)


async def test_a_new_client_id_marks_every_account_on_it_to_sign_in_again(
    client: httpx.AsyncClient, tenant: str
) -> None:
    credential, account = await _signed_in(client, tenant)
    assert (await _row(client, tenant, account))["state"] == "connected"
    changed = await client.patch(
        f"/v1/app-credentials/{credential}", json={"clientId": "signin-other"}, headers=admin(tenant)
    )
    assert changed.status_code == 200, changed.text
    data = changed.json()["data"]
    assert data["signInAgain"] == 1 and data["clientId"] == "signin-other", data
    row = await _row(client, tenant, account)
    assert row["state"] == "refused" and "signs in again" in str(row["stateReason"]), row


async def test_a_rename_alone_keeps_every_sign_in(client: httpx.AsyncClient, tenant: str) -> None:
    credential, account = await _signed_in(client, tenant)
    renamed = await client.patch(f"/v1/app-credentials/{credential}", json={"name": "Signin EU"}, headers=admin(tenant))
    assert renamed.status_code == 200 and renamed.json()["data"]["signInAgain"] == 0, renamed.text
    assert renamed.json()["data"]["name"] == "Signin EU"
    assert (await _row(client, tenant, account))["state"] == "connected"


async def test_only_a_team_admin_edits_a_credential(client: httpx.AsyncClient, tenant: str) -> None:
    credential = await team_credential(client, admin(tenant), APP, "signin-own", "s3cret")
    builder = person(tenant, "James Richardson", {TEAM: "builder"})
    refused = await client.patch(f"/v1/app-credentials/{credential}", json={"clientId": "x"}, headers=builder)
    assert refused.status_code == 403, refused.text
    kept = (await client.get(f"/v1/app-credentials/{credential}", headers=admin(tenant))).json()["data"]
    assert kept["clientId"] == "signin-own", "a refused edit changed nothing"


async def test_a_setting_its_app_does_not_register_and_ops_ais_app_are_refused(
    client: httpx.AsyncClient, tenant: str
) -> None:
    credential = await team_credential(client, admin(tenant), APP, "signin-own", "s3cret")
    unknown = await client.patch(
        f"/v1/app-credentials/{credential}", json={"settings": {"login_url": "https://x"}}, headers=admin(tenant)
    )
    assert unknown.status_code == 400 and unknown.json()["error"]["code"] == "credential_setting_unknown", unknown.text
    secret = await client.patch(
        f"/v1/app-credentials/{credential}", json={"clientSecret": "other"}, headers=admin(tenant)
    )
    assert secret.status_code == 400, "the secret is replaced on its own route: " + secret.text
    ops_ai = await client.patch(f"/v1/app-credentials/ops-ai:{APP}", json={"name": "x"}, headers=admin(tenant))
    assert ops_ai.status_code == 400 and ops_ai.json()["error"]["code"] == "ops_ai_app", ops_ai.text


async def test_an_account_reads_the_registrations_setting_from_its_credential(
    client: httpx.AsyncClient, tenant: str
) -> None:
    credential, account = await _signed_in(client, tenant, settings={"tenant": "contoso"})

    async def signs_in_at() -> str:
        url = str((await client.post(f"/v1/apps/{APP}/accounts/{account}/sign-in", json={}, headers=admin(tenant)))
                  .json()["data"]["authorizeUrl"])  # fmt: skip
        return urlsplit(url).path

    assert await signs_in_at() == "/oauth2/contoso/authorize"
    moved = await client.patch(
        f"/v1/app-credentials/{credential}", json={"settings": {"tenant": "fabrikam"}}, headers=admin(tenant)
    )
    assert moved.status_code == 200 and moved.json()["data"]["signInAgain"] == 1, moved.text
    assert await signs_in_at() == "/oauth2/fabrikam/authorize"
    detail = (await client.get(f"/v1/apps/{APP}/accounts/{account}", headers=admin(tenant))).json()["data"]
    assert detail["pluginSettings"]["tenant"] == "fabrikam", detail["pluginSettings"]


async def test_a_credentials_page_says_what_it_holds_and_may_hold(client: httpx.AsyncClient, tenant: str) -> None:
    credential = await team_credential(
        client, admin(tenant), APP, "signin-own", "s3cret", settings={"tenant": "contoso"}
    )
    page = (await client.get(f"/v1/app-credentials/{credential}", headers=admin(tenant))).json()["data"]
    assert page["settings"] == {"tenant": "contoso"}, page
    assert page["fields"] == [{"name": "tenant", "label": "Directory tenant", "help": None, "pem": False}], page
    custom = (
        await client.post("/v1/apps", json={"name": "Ledger", "authKind": "oauth2_auth_code"}, headers=admin(tenant))
    ).json()["data"]
    own = await team_credential(
        client, admin(tenant), custom["id"], "ledger-app", "s", settings={"tokenUrl": "https://login.ledger.test/t"}
    )
    shown = (await client.get(f"/v1/app-credentials/{own}", headers=admin(tenant))).json()["data"]
    names = [f["name"] for f in shown["fields"]]
    assert {"authorizeUrl", "tokenUrl", "signingCertificate"} <= set(names), names
    assert not {"clientId", "clientSecret", "scopes", "signingKey", "baseUrl"} & set(names), names
    assert next(f for f in shown["fields"] if f["name"] == "tokenUrl")["label"] == "Token address"
    assert shown["settings"] == {"tokenUrl": "https://login.ledger.test/t"}, shown
