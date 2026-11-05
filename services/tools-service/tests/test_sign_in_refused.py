"""A sign-in the system refuses, through the real routes, by failure mode: the person sees the system's code or a
generic failure instead of one sentence naming who acts; the plugin's sentence for one cause of a code is said for
another; the refusal is not recorded, so the account still reads as never tried; the same refusal can be handed
back twice; one person's refusal marks the team's account; and a refusal at the token exchange (a wrong client
secret) reads as a broken sign-in rather than as the secret to replace."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from .conftest import team_credential
from .test_review_decisions import person
from .test_sign_in_place import APP, TEAM, admin, signin_client


def wrong_secret() -> httpx.AsyncClient:
    """GitHub's answer to a wrong client secret: 200, with the error in the body and no token."""

    async def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "error": "incorrect_client_credentials",
                "error_description": "The client_id and/or client_secret passed are incorrect.",
            },
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


@pytest.fixture
async def client(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[httpx.AsyncClient]:
    async with signin_client(engine, seed, tenant, catalog_tools, upstream=wrong_secret()) as c:
        yield c


async def _started(client: httpx.AsyncClient, headers: dict[str, str], account: str, *, own: bool = False) -> str:
    """Starts a sign-in on the account; the state the system hands back."""
    path = f"/v1/apps/{APP}/accounts/{account}/sign-in"
    started = await client.post(path, json={"account": "self" if own else "team"}, headers=headers)
    assert started.status_code == 200, started.text
    url = str(started.json()["data"]["authorizeUrl"])
    return parse_qs(urlsplit(url).query)["state"][0]


async def _account(client: httpx.AsyncClient, tenant: str, **body: Any) -> str:
    on = await client.put(f"/v1/apps/{APP}/team", json={"enabled": True, **body}, headers=admin(tenant))
    assert on.status_code == 200, on.text
    return str(on.json()["data"]["connectionId"])


async def _complete(client: httpx.AsyncClient, headers: dict[str, str], account: str, **body: Any) -> httpx.Response:
    return await client.post("/v1/sign-ins/complete", json=body, headers=headers)


APP_NAME = "Signin desk"
REFUSALS = [
    # Two causes of one code: the description picks the entry, and the first that matches is said.
    ("invalid_client", "app must be installed into org", f"Install {APP_NAME}'s app in your org first.", "admin"),
    ("invalid_client", "client identifier invalid", f"{APP_NAME} does not know this app.", "admin"),
    (
        "OAUTH_APP_BLOCKED",
        "blocked by admin",
        f"Your admin has blocked {APP_NAME}'s app. Ask them to allow it.",
        "admin",
    ),
    # Codes the plugin does not name: the platform's own words.
    ("access_denied", "user denied", f"{APP_NAME} access was not given. Connect again to retry.", "person"),
    ("server_error", "In maintenance.", f"{APP_NAME} refused the sign-in: In maintenance.", "person"),
]


@pytest.mark.parametrize("refusal", REFUSALS, ids=[r[0] + "-" + r[1][:12] for r in REFUSALS])
async def test_a_refusal_answers_one_sentence_and_who_acts(
    client: httpx.AsyncClient, tenant: str, refusal: tuple[str, str, str, str]
) -> None:
    error, description, message, who = refusal
    account = await _account(client, tenant)
    state = await _started(client, admin(tenant), account)
    refused = await _complete(client, admin(tenant), account, state=state, error=error, errorDescription=description)
    assert refused.status_code == 422, refused.text
    body = refused.json()["error"]
    assert body["code"] == "sign_in_refused" and body["message"] == message, body
    said = {"message": message, "who": who, "providerCode": error, "appId": APP, "app": "Signin desk"}
    assert body["details"] == said, body


async def test_a_refusal_is_recorded_and_the_account_reads_refused(client: httpx.AsyncClient, tenant: str) -> None:
    account = await _account(client, tenant)
    state = await _started(client, admin(tenant), account)
    await _complete(client, admin(tenant), account, state=state, error="OAUTH_APP_BLOCKED")
    said = "Your admin has blocked Signin desk's app. Ask them to allow it."
    page = (await client.get(f"/v1/apps/{APP}", headers=admin(tenant))).json()["data"]
    row = next(a for a in page["accounts"] if a["id"] == account)
    assert (row["state"], row["stateReason"]) == ("refused", said), row
    assert row["health"]["status"] == "failed" and row["health"]["message"] == said, row["health"]
    assert page["card"]["appState"] == "needs_sign_in" and page["card"]["appStateReason"] == said, page["card"]


async def test_a_refusal_uses_up_its_state(client: httpx.AsyncClient, tenant: str) -> None:
    account = await _account(client, tenant)
    state = await _started(client, admin(tenant), account)
    first = await _complete(client, admin(tenant), account, state=state, error="access_denied")
    again = await _complete(client, admin(tenant), account, state=state, error="access_denied")
    guessed = await _complete(client, admin(tenant), account, state="x" * 43, error="access_denied")
    assert first.status_code == 422, first.text
    assert [r.json()["error"]["code"] for r in (again, guessed)] == ["sign_in_expired"] * 2, (again.text, guessed.text)
    blank = await _complete(client, admin(tenant), account, state=await _started(client, admin(tenant), account))
    assert blank.status_code == 400, blank.text


async def test_one_persons_refusal_leaves_the_team_account_as_it_was(client: httpx.AsyncClient, tenant: str) -> None:
    account = await _account(client, tenant, signIn="person")
    james = person(tenant, "James Richardson", {TEAM: "builder"})
    state = await _started(client, james, account, own=True)
    refused = await _complete(client, james, account, state=state, error="access_denied")
    assert refused.status_code == 422 and refused.json()["error"]["details"]["who"] == "person", refused.text
    detail = (await client.get(f"/v1/apps/{APP}/accounts/{account}", headers=admin(tenant))).json()["data"]
    assert detail["status"] != "needs_reconnect" and detail["health"]["account"] == "own", detail


async def test_a_wrong_client_secret_at_the_token_exchange_names_the_credential_to_fix(
    client: httpx.AsyncClient, tenant: str
) -> None:
    credential = await team_credential(client, admin(tenant), APP, "signin-own", "wrong-secret", name="Signin prod")
    account = await _account(client, tenant, credentialId=credential)
    state = await _started(client, admin(tenant), account)
    refused = await _complete(client, admin(tenant), account, state=state, code="the-code")
    assert refused.status_code == 422, refused.text
    said = "The client secret for Signin prod is wrong. Replace it on its Credentials page."
    assert refused.json()["error"]["details"] == {
        "message": said,
        "who": "admin",
        "providerCode": "incorrect_client_credentials",
        "appId": APP,
        "app": "Signin desk",
    }, refused.text
    page = (await client.get(f"/v1/apps/{APP}", headers=admin(tenant))).json()["data"]
    assert next(a for a in page["accounts"] if a["id"] == account)["state"] == "refused", page["accounts"]


async def test_a_sign_in_finishes_from_its_state_in_a_window_that_knows_nothing_else(
    client: httpx.AsyncClient, tenant: str
) -> None:
    """The return page holds only what the system sent back; the state names the account, its app and its team, so
    a window that started nothing (another tab, a fresh browser) finishes the sign-in that the state was sent for."""
    account = await _account(client, tenant)
    state = await _started(client, admin(tenant), account)
    assert state.startswith(f"{TEAM}."), state
    finished = await client.post(
        "/v1/sign-ins/complete", json={"state": state, "error": "access_denied"}, headers=admin(tenant)
    )
    assert finished.status_code == 422, finished.text
    details = finished.json()["error"]["details"]
    assert (details["appId"], details["app"]) == (APP, "Signin desk"), details
