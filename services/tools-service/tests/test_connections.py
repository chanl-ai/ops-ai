"""Connections through the real routes with people signed in on platform-style tokens (c-330): who may change one,
secret parts written once and never read back, a stale write storing nothing, a connection in use kept, and a sign-in
finished once, by the person who started it, before it expires."""

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
    res = await c.post("/v1/connections", json={"name": "Core banking API", "authKind": kind}, headers=who)
    assert res.status_code == 201, res.text
    return res.json()["data"]


async def test_only_someone_who_manages_connections_changes_one(client: httpx.AsyncClient, tenant: str) -> None:
    builder = person(tenant, "James Richardson", {TEAM: "builder"})
    refused = await client.post("/v1/connections", json={"name": "x", "authKind": "api_key"}, headers=builder)
    assert refused.status_code == 403, refused.text
    service = await client.post(
        "/v1/connections",
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
    put = await client.put(f"/v1/connections/{conn['id']}/environments/test", json=body, headers=builder)
    assert put.status_code == 403, put.text
    # Every member reads them, and is told whether they may manage them.
    read = await client.get(f"/v1/connections/{conn['id']}", headers=builder)
    assert read.status_code == 200 and read.json()["data"]["mayManage"] is False
    listed = await client.get("/v1/connections", headers=builder)
    assert [r["id"] for r in listed.json()["data"]["data"]] == [conn["id"]] or conn["id"] in str(listed.json())


async def test_a_secret_part_is_written_once_and_never_read_back(client: httpx.AsyncClient, tenant: str) -> None:
    who = admin(tenant)
    conn = await _made(client, who)
    body = {
        "revision": conn["revision"],
        "settings": {"name": "X-Api-Key", "baseUrl": BASE},
        "secretValues": {"key": "k-secret-1"},
    }
    put = await client.put(f"/v1/connections/{conn['id']}/environments/test", json=body, headers=who)
    assert put.status_code == 200, put.text
    detail = put.json()["data"]
    assert detail["environments"]["test"]["secrets"]["key"]["set"] is True
    assert detail["environments"]["production"]["set"] is False
    assert "k-secret-1" not in put.text
    secrets = (await client.get("/v1/secrets", headers=who)).json()["data"]
    part = next(s for s in secrets if s["name"] == secret_name(conn["id"], "test", "key"))
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
    assert (
        await client.put(f"/v1/connections/{conn['id']}/environments/test", json=first, headers=who)
    ).status_code == 200
    stale = {
        "revision": conn["revision"],
        "settings": {"username": "ops", "baseUrl": BASE},
        "secretValues": {"password": "p-2"},
    }
    lost = await client.put(f"/v1/connections/{conn['id']}/environments/production", json=stale, headers=who)
    assert lost.status_code == 409 and lost.json()["error"]["code"] == "stale_version", lost.text
    names = [s["name"] for s in (await client.get("/v1/secrets", headers=who)).json()["data"]]
    assert secret_name(conn["id"], "production", "password") not in names


async def test_settings_are_checked_against_the_kind(client: httpx.AsyncClient, tenant: str) -> None:
    who = admin(tenant)
    conn = await _made(client, who, "oauth2_client_credentials")
    path = f"/v1/connections/{conn['id']}/environments/test"
    plain_secret = {
        "revision": 1,
        "settings": {"tokenUrl": "https://x.test/t", "clientId": "c", "clientSecret": "s", "baseUrl": BASE},
    }
    assert (await client.put(path, json=plain_secret, headers=who)).status_code == 400
    unknown = {
        "revision": 1,
        "settings": {"tokenUrl": "https://x.test/t", "clientId": "c", "colour": "red", "baseUrl": BASE},
    }
    assert (await client.put(path, json=unknown, headers=who)).status_code == 400
    http = {
        "revision": 1,
        "settings": {"tokenUrl": "http://x.test/t", "clientId": "c", "baseUrl": BASE},
        "secretValues": {"clientSecret": "s"},
    }
    assert (await client.put(path, json=http, headers=who)).status_code == 400
    no_secret = {"revision": 1, "settings": {"tokenUrl": "https://x.test/t", "clientId": "c", "baseUrl": BASE}}
    assert (await client.put(path, json=no_secret, headers=who)).status_code == 400


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
    refused = await client.delete(f"/v1/connections/{conn['id']}", headers=who)
    assert refused.status_code == 409 and refused.json()["error"]["details"]["modules"] == ["Ledger"], refused.text
    detail = (await client.get(f"/v1/connections/{conn['id']}", headers=who)).json()["data"]
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
    put = await client.put(
        f"/v1/connections/{conn['id']}/environments/test", json={"revision": 1, "settings": settings}, headers=who
    )
    assert put.status_code == 200, put.text
    started = await client.post(f"/v1/connections/{conn['id']}/sign-in", json={"environment": "test"}, headers=who)
    assert started.status_code == 200, started.text
    url = str(started.json()["data"]["authorizeUrl"])
    query = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert url.startswith(AUTHORIZE) and query["code_challenge_method"] == "S256" and len(query["code_challenge"]) == 43
    assert query["redirect_uri"].endswith("/connections/sign-in/return")
    return conn, query["state"]


async def test_a_sign_in_is_finished_once_by_who_started_it(client: httpx.AsyncClient, tenant: str) -> None:
    conn, state = await _signing_in(client, tenant)
    path = f"/v1/connections/{conn['id']}/sign-in/complete"
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
            "environment": "test",
            "person_id": "usr_priya|priya@bank.example",
            "verifier_ct": "x",
            "redirect_uri": "https://console.bank.test/connections/sign-in/return",
            "expires_at": now - timedelta(seconds=1),
        },
        now=now - timedelta(minutes=20),
    )
    res = await client.post(
        f"/v1/connections/{conn['id']}/sign-in/complete",
        json={"state": "old-state-0123456789", "code": "c"},
        headers=admin(tenant),
    )
    assert res.status_code == 400 and res.json()["error"]["code"] == "sign_in_expired", res.text


async def test_a_team_reads_only_its_own_connections_an_all_scope_team_included(
    client: httpx.AsyncClient, tenant: str
) -> None:
    """c-509: an all-scope team (the seed's Platform team) listed and read every team's connections, a sharing across
    teams the team-is-the-workspace rule does not allow."""
    cards = person(tenant, "Carla Cards", {"team_cards": "admin"})
    theirs = await _made(client, cards)
    platform = admin(tenant)
    listed = (await client.get("/v1/connections", params={"pageSize": 100}, headers=platform)).json()["data"]["data"]
    assert theirs["id"] not in {c["id"] for c in listed}, listed
    read = await client.get(f"/v1/connections/{theirs['id']}", headers=platform)
    assert read.status_code == 404 and "team_cards" not in read.text, read.text


async def test_a_connection_made_available_to_another_team_stays_its_own(
    client: httpx.AsyncClient, tenant: str
) -> None:
    """c-509: `availableTo` let another team's modules sign in with this team's connection; an old caller still sending
    it is answered and the field ignored."""
    body = {"name": "Shared ledger", "authKind": "api_key", "availableTo": ["team_cards"]}
    made = await client.post("/v1/connections", json=body, headers=admin(tenant))
    assert made.status_code == 201 and made.json()["data"]["availableTo"] == [], made.text
    cards = person(tenant, "Carla Cards", {"team_cards": "admin"})
    read = await client.get(f"/v1/connections/{made.json()['data']['id']}", headers=cards)
    assert read.status_code == 404, read.text


async def test_each_team_holding_a_seeded_module_signs_in_with_its_own_connection(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str
) -> None:
    """c-509: the seed's connections all belonged to its all-scope team, so once a connection serves only its own team,
    every other team's seeded module lost its sign-in, and Operations could not use the seeded core banking one."""
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC))
    store, conns = ModuleStore(engine), ConnectionStore(engine)
    core = await conns.get(tenant, "int_core_banking")
    assert core is not None and core["team_id"] == "team_ops", core
    with_connection = [m for m in await store.all(tenant) if m["connection_id"]]
    assert with_connection, "the seed binds modules to its connections"
    for m in with_connection:
        conn = await conns.get(tenant, m["connection_id"])
        assert conn is not None and conn["team_id"] == m["team_id"], (m["id"], m["team_id"], conn and conn["team_id"])
