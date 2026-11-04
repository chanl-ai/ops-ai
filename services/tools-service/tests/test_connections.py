"""A custom app's accounts through the real routes with people signed in on platform-style tokens: who may
change one, secret parts written once and never read back, a stale write storing nothing, an account in use kept, and a
sign-in finished once, by the person who started it, before it expires."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_service_kit.settings import Settings
from ops_tools.connections.service import secret_name
from ops_tools.modules.seed import load
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, response_checker, service_headers
from .test_review_decisions import introspect, jwks, person

TEAM = "team_platform"
AUTHORIZE = "https://login.bank.test/authorize"
BASE = "https://ledger.test"


@pytest.fixture
async def client(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[httpx.AsyncClient]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    settings = Settings()
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes),
    )
    app = build_app(engine, seed, tenant, auth=auth)
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        yield c


def admin(tenant: str) -> dict[str, str]:
    return person(tenant, "Priya Shah", {TEAM: "admin"})


async def _made(c: httpx.AsyncClient, who: dict[str, str], kind: str = "api_key") -> dict[str, Any]:
    res = await c.post("/v1/apps", json={"name": "Core banking API", "authKind": kind}, headers=who)
    assert res.status_code == 201, res.text
    return res.json()["data"]


def _at(account: dict[str, Any]) -> str:
    return f"/v1/apps/{account['appId']}/accounts/{account['id']}"


async def test_only_someone_who_manages_connections_changes_one(client: httpx.AsyncClient, tenant: str) -> None:
    builder = person(tenant, "James Richardson", {TEAM: "builder"})
    refused = await client.post("/v1/apps", json={"name": "x", "authKind": "api_key"}, headers=builder)
    assert refused.status_code == 403, refused.text
    service = await client.post(
        "/v1/apps",
        json={"name": "x", "authKind": "api_key"},
        headers={**service_headers(tenant), "X-Team-Id": TEAM},
    )
    # A service token is refused whatever scopes it claims: a credential is entered by a person.
    assert service.status_code in (401, 403), service.text
    conn = await _made(client, admin(tenant))
    body = {
        "revision": conn["revision"],
        "settings": {"name": "X-Api-Key", "baseUrl": BASE},
        "secretValues": {"key": "k-1"},
    }
    put = await client.patch(_at(conn), json=body, headers=builder)
    assert put.status_code == 403, put.text
    # Every member reads them, and is told whether they may manage them.
    read = await client.get(_at(conn), headers=builder)
    assert read.status_code == 200 and read.json()["data"]["mayManage"] is False
    listed = await client.get("/v1/apps", headers=builder)
    assert conn["id"] in {c["id"] for c in listed.json()["data"]}, listed.text


async def test_a_secret_part_is_written_once_and_never_read_back(client: httpx.AsyncClient, tenant: str) -> None:
    who = admin(tenant)
    conn = await _made(client, who)
    body = {
        "revision": conn["revision"],
        "settings": {"name": "X-Api-Key", "baseUrl": BASE},
        "secretValues": {"key": "k-secret-1"},
    }
    put = await client.patch(_at(conn), json=body, headers=who)
    assert put.status_code == 200, put.text
    detail = put.json()["data"]
    assert detail["secrets"]["key"]["set"] is True
    assert "k-secret-1" not in put.text
    secrets = (await client.get("/v1/secrets", headers=who)).json()["data"]
    part = next(s for s in secrets if s["name"] == secret_name(conn["id"], "key"))
    assert part["connectionId"] == conn["id"] and "k-secret-1" not in str(secrets)
    for method, path, payload in (
        ("post", f"/v1/secrets/{part['name']}/rotate", {"value": "other"}),
        ("delete", f"/v1/secrets/{part['name']}", None),
    ):
        res = await client.request(method, path, json=payload, headers=who)
        assert res.status_code == 409 and res.json()["error"]["code"] == "connection_secret", res.text


async def test_a_stale_write_stores_no_value(client: httpx.AsyncClient, tenant: str) -> None:
    who = admin(tenant)
    conn = await _made(client, who, "basic")
    first = {
        "revision": conn["revision"],
        "settings": {"username": "ops", "baseUrl": BASE},
        "secretValues": {"password": "p-1"},
    }
    assert (await client.patch(_at(conn), json=first, headers=who)).status_code == 200
    held = await client.get("/v1/secrets", headers=who)
    version = next(s["version"] for s in held.json()["data"] if s["name"] == secret_name(conn["id"], "password"))
    stale = {
        "revision": conn["revision"],
        "settings": {"username": "ops", "baseUrl": BASE},
        "secretValues": {"password": "p-2"},
    }
    lost = await client.patch(_at(conn), json=stale, headers=who)
    assert lost.status_code == 409 and lost.json()["error"]["code"] == "stale_version", lost.text
    after = (await client.get("/v1/secrets", headers=who)).json()["data"]
    assert next(s["version"] for s in after if s["name"] == secret_name(conn["id"], "password")) == version


async def test_settings_are_checked_against_the_kind(client: httpx.AsyncClient, tenant: str) -> None:
    who = admin(tenant)
    conn = await _made(client, who, "oauth2_client_credentials")
    path = _at(conn)
    plain_secret = {
        "revision": 1,
        "settings": {"tokenUrl": "https://x.test/t", "clientId": "c", "clientSecret": "s", "baseUrl": BASE},
    }
    assert (await client.patch(path, json=plain_secret, headers=who)).status_code == 400
    unknown = {
        "revision": 1,
        "settings": {"tokenUrl": "https://x.test/t", "clientId": "c", "colour": "red", "baseUrl": BASE},
    }
    assert (await client.patch(path, json=unknown, headers=who)).status_code == 400
    http = {
        "revision": 1,
        "settings": {"tokenUrl": "http://x.test/t", "clientId": "c", "baseUrl": BASE},
        "secretValues": {"clientSecret": "s"},
    }
    assert (await client.patch(path, json=http, headers=who)).status_code == 400
    no_secret = {"revision": 1, "settings": {"tokenUrl": "https://x.test/t", "clientId": "c", "baseUrl": BASE}}
    assert (await client.patch(path, json=no_secret, headers=who)).status_code == 400


async def test_a_connection_in_use_is_not_deleted(client: httpx.AsyncClient, tenant: str) -> None:
    who = admin(tenant)
    security = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    assert (await client.post("/v1/egress/hosts", json={"value": "ledger.test"}, headers=security)).status_code == 201
    conn = await _made(client, who)
    body = {
        "name": "ledger",
        "displayName": "Ledger",
        "system": "Ledger",
        "type": "http",
        "endpoint": "",
        "connectionId": conn["id"],
        "http": {
            "name": "ledger_read",
            "description": "d",
            "access": "read",
            "method": "GET",
            "url": "https://ledger.test/a",
        },
    }
    made = await client.post(
        "/v1/tool-modules", json=body, headers=person(tenant, "James Richardson", {TEAM: "builder"})
    )
    assert made.status_code == 201, made.text
    refused = await client.delete(_at(conn), headers=who)
    assert refused.status_code == 409 and refused.json()["error"]["details"]["modules"] == ["Ledger"], refused.text
    detail = (await client.get(_at(conn), headers=who)).json()["data"]
    assert detail["usedBy"] == [{"id": made.json()["data"]["id"], "name": "Ledger"}]


async def _signing_in(client: httpx.AsyncClient, tenant: str) -> tuple[dict[str, Any], str]:
    who = admin(tenant)
    security = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    assert (
        await client.post("/v1/egress/hosts", json={"value": "login.bank.test"}, headers=security)
    ).status_code == 201
    conn = await _made(client, who, "oauth2_auth_code")
    settings = {
        "authorizeUrl": AUTHORIZE,
        "tokenUrl": "https://login.bank.test/token",
        "clientId": "ops-console",
        "baseUrl": BASE,
    }
    put = await client.patch(_at(conn), json={"revision": 1, "settings": settings}, headers=who)
    assert put.status_code == 200, put.text
    started = await client.post(f"{_at(conn)}/sign-in", json={}, headers=who)
    assert started.status_code == 200, started.text
    url = str(started.json()["data"]["authorizeUrl"])
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert url.startswith(AUTHORIZE) and query["code_challenge_method"] == "S256" and len(query["code_challenge"]) == 43
    assert query["redirect_uri"].endswith("/connections/sign-in/return")
    # The return page finishes the sign-in under the account's app.
    assert started.json()["data"]["appId"] == conn["appId"], started.text
    return conn, query["state"]


async def test_a_sign_in_is_finished_once_by_who_started_it(client: httpx.AsyncClient, tenant: str) -> None:
    conn, state = await _signing_in(client, tenant)
    path = f"{_at(conn)}/sign-in/complete"
    other = person(tenant, "Maya Okafor", {TEAM: "admin"})
    stolen = await client.post(path, json={"state": state, "code": "c"}, headers=other)
    assert stolen.status_code == 400 and stolen.json()["error"]["code"] == "sign_in_expired", stolen.text
    # The other person's attempt did not spend it: the person who started reaches the token exchange, which this test's
    # system does not answer.
    mine = await client.post(path, json={"state": state, "code": "c"}, headers=admin(tenant))
    assert mine.json()["error"]["code"] == "sign_in_failed", mine.text
    replay = await client.post(path, json={"state": state, "code": "c"}, headers=admin(tenant))
    assert replay.json()["error"]["code"] == "sign_in_expired", replay.text


async def test_an_expired_sign_in_is_refused(client: httpx.AsyncClient, tenant: str, engine: AsyncEngine) -> None:
    conn, _ = await _signing_in(client, tenant)
    store = ConnectionStore(engine)
    now = datetime.now(UTC)
    import hashlib  # noqa: PLC0415 - the one test that writes a state by hand

    await store.add_state(
        {
            "tenant_id": tenant,
            "state_hash": hashlib.sha256(b"old-state-0123456789").hexdigest(),
            "connection_id": conn["id"],
            "person_id": "usr_priya|priya@bank.example",
            "verifier_ct": "x",
            "redirect_uri": "https://console.bank.test/connections/sign-in/return",
            "expires_at": now - timedelta(seconds=1),
        },
        now=now - timedelta(minutes=20),
    )
    res = await client.post(
        f"{_at(conn)}/sign-in/complete",
        json={"state": "old-state-0123456789", "code": "c"},
        headers=admin(tenant),
    )
    assert res.status_code == 400 and res.json()["error"]["code"] == "sign_in_expired", res.text


async def test_a_team_reads_only_its_own_connections_an_all_scope_team_included(
    client: httpx.AsyncClient, tenant: str
) -> None:
    """An all-scope team (the seed's Platform team) listed and read every team's connections, a sharing across
    teams the team-is-the-workspace rule does not allow."""
    cards = person(tenant, "Carla Cards", {"team_cards": "admin"})
    theirs = await _made(client, cards)
    platform = admin(tenant)
    listed = (await client.get("/v1/apps", headers=platform)).json()["data"]
    assert theirs["id"] not in {c["id"] for c in listed}, listed
    read = await client.get(_at(theirs), headers=platform)
    assert read.status_code == 404 and "team_cards" not in read.text, read.text


async def test_each_team_holding_a_seeded_module_signs_in_with_its_own_connection(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str
) -> None:
    """The seed's connections all belonged to its all-scope team, so once a connection serves only its own team,
    every other team's seeded module lost its sign-in. A seeded connection is made only where a module uses it:
    Operations held twenty cards no tool used."""
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC))
    store, conns = ModuleStore(engine), ConnectionStore(engine)
    used = {(m["connection_id"], m["team_id"]) for m in await store.all(tenant) if m["connection_id"]}
    teams = ["team_ops", *(str(t["id"]) for t in seed.get("teams", []))]
    seeded = [c for c in await conns.page(tenant, teams, "", 0, 500) if c["created_by"] == "seed"]
    assert seeded and all((c["id"], c["team_id"]) in used for c in seeded), [c["id"] for c in seeded]
    with_connection = [m for m in await store.all(tenant) if m["connection_id"]]
    assert with_connection, "the seed binds modules to its connections"
    for m in with_connection:
        conn = await conns.get(tenant, m["connection_id"])
        assert conn is not None and conn["team_id"] == m["team_id"], (m["id"], m["team_id"], conn and conn["team_id"])


async def test_a_connection_made_each_person_with_the_team_as_backup_has_the_backup_on(
    client: httpx.AsyncClient, tenant: str
) -> None:
    """The console's and a plugin's create send only `signIn`; made as person_or_team with the backup off, a workflow
    run with nobody behind it was refused CONNECTION_NOT_LINKED though the team account was signed in."""
    body = {"name": "Case desk", "authKind": "oauth2_auth_code", "signIn": "person_or_team"}
    made = await client.post("/v1/apps", json=body, headers=admin(tenant))
    assert made.status_code == 201, made.text
    assert made.json()["data"]["signIn"] == "person_or_team" and made.json()["data"]["teamBackup"] is True, made.text
    team_only = await client.post("/v1/apps", json={**body, "signIn": "team"}, headers=admin(tenant))
    assert team_only.json()["data"]["teamBackup"] is False, team_only.text
