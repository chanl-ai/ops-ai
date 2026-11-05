"""An app's accounts and whether the app is on for the team, by failure mode: Add account is refused until some
other way made the app's first account; an account signed in while its app is off stays behind it, so its calls are
refused as "off for this team" while the page reads Available. Rig: test_app_credential_edit (a system that grants
every code)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from .conftest import team_credential
from .test_app_credential_edit import granting
from .test_sign_in_place import APP, admin, signin_client
from .test_sign_in_refused import _account, _complete, _started  # pyright: ignore[reportPrivateUsage]


@pytest.fixture
async def client(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[httpx.AsyncClient]:
    async with signin_client(engine, seed, tenant, catalog_tools, upstream=granting()) as c:
        yield c


async def _card(client: httpx.AsyncClient, tenant: str) -> dict[str, Any]:
    return (await client.get(f"/v1/apps/{APP}", headers=admin(tenant))).json()["data"]["card"]


async def test_add_account_makes_the_apps_first_account_when_it_has_none(
    client: httpx.AsyncClient, tenant: str
) -> None:
    credential = await team_credential(client, admin(tenant), APP, "signin-own", "s3cret-value")
    made = await client.post(
        f"/v1/apps/{APP}/accounts", json={"name": "First org", "credentialId": credential}, headers=admin(tenant)
    )
    assert made.status_code == 201, made.text
    card = await _card(client, tenant)
    assert card["connectionId"] == made.json()["data"]["id"] and card["plugin"]["teamOn"], card


async def test_signing_in_turns_the_app_on_and_the_page_reads_connected(client: httpx.AsyncClient, tenant: str) -> None:
    credential = await team_credential(client, admin(tenant), APP, "signin-own", "s3cret-value")
    account = await _account(client, tenant, credentialId=credential)
    off = await client.put(f"/v1/apps/{APP}/team", json={"enabled": False}, headers=admin(tenant))
    assert off.status_code == 200, off.text
    assert not (await _card(client, tenant))["plugin"]["teamOn"]

    state = await _started(client, admin(tenant), account)
    done = await _complete(client, admin(tenant), account, state=state, code="the-code")
    assert done.status_code == 200, done.text
    card = await _card(client, tenant)
    assert card["plugin"]["teamOn"] and card["connectionId"] == account and card["appState"] == "connected", card
