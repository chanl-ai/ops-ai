"""An app credential set and checked by a team admin (group B), by failure mode: saving the team's own client
drops the environment's addresses or is refused for them; Test with my account keeps a token, so a check replaces the
team account; it signs in with a client other than the environment's; and someone who may not set app credentials
can check them."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.store.connections import SHARED, ConnectionStore

from . import test_personal_sign_in as rig
from .test_personal_sign_in import SETTINGS, TEAM, System
from .test_review_decisions import person

# The sign-in rig's fixtures: the app with a fake system whose token endpoint answers any code.
client, system = rig.client, rig.system


def admin(tenant: str) -> dict[str, str]:
    return person(tenant, "Priya Shah", {TEAM: "admin"})


async def team_app(client: httpx.AsyncClient, tenant: str) -> str:
    security = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    await client.post("/v1/egress/hosts", json={"value": "login.bank.test"}, headers=security)
    made = await client.post(
        "/v1/connections", json={"name": "CRM", "authKind": "oauth2_auth_code", "signIn": "team"}, headers=admin(tenant)
    )
    assert made.status_code == 201, made.text
    conn = str(made.json()["data"]["id"])
    put = await client.put(
        f"/v1/connections/{conn}/environments/test", json={"revision": 1, "settings": SETTINGS}, headers=admin(tenant)
    )
    assert put.status_code == 200, put.text
    return conn


async def test_the_teams_own_client_is_saved_and_the_addresses_stay(client: httpx.AsyncClient, tenant: str) -> None:
    conn = await team_app(client, tenant)
    detail = (await client.get(f"/v1/connections/{conn}", headers=admin(tenant))).json()["data"]
    body = {"revision": detail["revision"], "settings": {"clientId": "own-app"}, "secretValues": {"clientSecret": "s3"}}
    put = await client.put(f"/v1/connections/{conn}/environments/test", json=body, headers=admin(tenant))
    assert put.status_code == 200, put.text
    settings = put.json()["data"]["environments"]["test"]["settings"]
    assert {k: settings.get(k) for k in ("clientId", "authorizeUrl", "tokenUrl", "baseUrl")} == {
        "clientId": "own-app",
        "authorizeUrl": SETTINGS["authorizeUrl"],
        "tokenUrl": SETTINGS["tokenUrl"],
        "baseUrl": SETTINGS["baseUrl"],
    }, settings


async def test_a_credential_check_signs_in_through_the_app_and_keeps_no_token(
    client: httpx.AsyncClient,
    system: System,
    engine: AsyncEngine,
    tenant: str,
) -> None:
    conn = await team_app(client, tenant)
    url = f"/v1/connections/{conn}/test-credential"
    started = await client.post(url, json={"environment": "test"}, headers=admin(tenant))
    assert started.status_code == 200, started.text
    query = parse_qs(urlsplit(str(started.json()["data"]["authorizeUrl"])).query)
    assert query["client_id"] == ["ops-console"]
    done = await client.post(url, json={"state": query["state"][0], "code": "priya"}, headers=admin(tenant))
    assert done.status_code == 200, done.text
    assert done.json()["data"]["health"]["status"] == "ok", done.text
    assert system.asked[-1]["code"] == "priya"
    assert await ConnectionStore(engine).token(tenant, conn, "test", SHARED) is None


async def test_a_builder_may_not_check_an_app_credential(client: httpx.AsyncClient, tenant: str) -> None:
    conn = await team_app(client, tenant)
    builder = person(tenant, "James Richardson", {TEAM: "builder"})
    r = await client.post(f"/v1/connections/{conn}/test-credential", json={"environment": "test"}, headers=builder)
    assert r.status_code == 403, r.text
