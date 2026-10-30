"""Each person's own sign-in on a connection (c-558), by failure mode: two people's calls carry each other's token or
the team's, a person with no sign-in is quietly given the team's, a call with nobody behind it uses a token nobody
allowed, one person's refused refresh stops everyone, a connect link is opened by someone else, reused or kept past its
time, starting your own sign-in needs the right to manage the connection, an operation's scopes are not asked for or a
token lacking one is sent anyway, a sign-in whose answer names no scopes is granted none, and a person sees another's
sign-ins or Disconnect leaves their token held at the system."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import ActingForPerson, Auth, Identity, ServiceAuth, service_verifiers
from ops_policy import AesGcmCipher
from ops_service_kit.settings import Settings
from ops_tools.auth import Authenticator, AuthFailed
from ops_tools.auth.tokens import Tokens
from ops_tools.connections.connect_links import ConnectLinks
from ops_tools.modules.seed import load
from ops_tools.store.connections import SHARED, ConnectionStore
from ops_tools.store.modules import ModuleStore

from .conftest import CONSOLE_URL, build_app, response_checker
from .test_review_decisions import introspect, jwks, person

TEAM = "team_platform"
BASE = "https://crm.bank.test"
SETTINGS = {
    "baseUrl": BASE,
    "authorizeUrl": "https://login.bank.test/authorize",
    "tokenUrl": "https://login.bank.test/token",
    "clientId": "ops-console",
    "scopes": "openid api",
}
JAMES = ActingForPerson(sub="usr_james", email="james@bank.example", name="James", team_id=TEAM)
MAYA = ActingForPerson(sub="usr_maya", email="maya@bank.example", name="Maya", team_id=TEAM)


class AnyUrl:
    async def check_url(self, tenant_id: str, url: str) -> str:
        return "login.bank.test"


def refusing() -> httpx.AsyncClient:
    """A token endpoint that refuses every refresh, as a system does once a person's grant is revoked."""

    async def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


async def connection(store: ConnectionStore, tenant: str, sign_in: str, *, backup: bool = False) -> str:
    now = datetime.now(UTC)
    row = {
        "tenant_id": tenant,
        "id": f"con_{sign_in}",
        "team_id": TEAM,
        "name": "CRM",
        "auth_kind": "oauth2_auth_code",
        "available_to": None,
        "sign_in": sign_in,
        "team_backup": backup,
        "status": "healthy",
        "revision": 1,
        "created_by": "t",
        "created_at": now,
        "updated_by": "t",
        "updated_at": now,
    }
    assert await store.create(row, actor="t", at=now)
    await store.change(tenant, f"con_{sign_in}", 1, {}, actor="t", at=now, environment=("test", SETTINGS, {}))
    return f"con_{sign_in}"


def module(tenant: str, connection_id: str) -> dict[str, Any]:
    return {"tenant_id": tenant, "team_id": TEAM, "connection_id": connection_id, "endpoint": BASE}


def rig(
    engine: AsyncEngine, upstream: httpx.AsyncClient | None = None
) -> tuple[ConnectionStore, Tokens, Authenticator]:
    store = ConnectionStore(engine)
    tokens = Tokens(store, AesGcmCipher(Settings().secrets_key.get_secret_value()), upstream, AnyUrl())  # pyright: ignore[reportArgumentType]
    return store, tokens, Authenticator(store, None, tokens, ConnectLinks(store, CONSOLE_URL))


async def bearer(
    auth: Authenticator, tenant: str, conn: str, who: ActingForPerson | None, scopes: tuple[str, ...] = ()
) -> str:
    prepared = await auth.prepare(
        module(tenant, conn), "test", tool="crm_update", actor="t", acting_for=who, scopes=scopes
    )
    assert prepared is not None
    return prepared.headers["Authorization"]


async def test_each_persons_call_carries_their_own_token_never_anothers_or_the_teams(
    engine: AsyncEngine, tenant: str
) -> None:
    store, tokens, auth = rig(engine)
    conn = await connection(store, tenant, "person")
    for who, token in ((SHARED, "at-team"), (JAMES.sub, "at-james"), (MAYA.sub, "at-maya")):
        await tokens.store_answer(tenant, conn, "test", {"access_token": token, "expires_in": 3600}, who)
    assert await bearer(auth, tenant, conn, JAMES) == "Bearer at-james"
    assert await bearer(auth, tenant, conn, MAYA) == "Bearer at-maya"


async def test_a_person_with_no_sign_in_gets_a_link_made_for_them_not_the_teams_token(
    engine: AsyncEngine, tenant: str
) -> None:
    store, tokens, auth = rig(engine)
    conn = await connection(store, tenant, "person_or_team", backup=True)
    await tokens.store_answer(tenant, conn, "test", {"access_token": "at-team", "expires_in": 3600})
    with pytest.raises(AuthFailed) as e:
        await bearer(auth, tenant, conn, JAMES)
    assert e.value.code == "CONNECTION_NOT_LINKED" and e.value.details["reason"] == "not_connected"
    url = str(e.value.details["connectUrl"])
    link = parse_qs(urlsplit(url).query)["link"][0]
    assert url.startswith(f"{CONSOLE_URL}/connections/connect?")
    row = await store.link(tenant, hashlib.sha256(link.encode()).hexdigest())
    assert row is not None and (row["person_id"], row["team_id"], row["connection_id"]) == (JAMES.sub, TEAM, conn)


async def test_a_call_with_nobody_behind_it_uses_the_team_account_only_where_the_backup_is_on(
    engine: AsyncEngine, tenant: str
) -> None:
    store, tokens, auth = rig(engine)
    personal = await connection(store, tenant, "person")
    backed = await connection(store, tenant, "person_or_team", backup=True)
    for conn in (personal, backed):
        await tokens.store_answer(tenant, conn, "test", {"access_token": "at-team", "expires_in": 3600})
    with pytest.raises(AuthFailed) as e:
        await bearer(auth, tenant, personal, None)
    assert e.value.code == "CONNECTION_NOT_LINKED" and e.value.details["reason"] == "no_person"
    assert await bearer(auth, tenant, backed, None) == "Bearer at-team"


async def test_one_persons_refused_refresh_leaves_the_connection_and_everyone_else_working(
    engine: AsyncEngine, tenant: str
) -> None:
    store, tokens, auth = rig(engine, refusing())
    conn = await connection(store, tenant, "person")
    spent = {"access_token": "at-old", "refresh_token": "rt-old", "expires_in": 1}
    await tokens.store_answer(tenant, conn, "test", spent, JAMES.sub)
    await tokens.store_answer(tenant, conn, "test", {"access_token": "at-maya", "expires_in": 3600}, MAYA.sub)
    with pytest.raises(AuthFailed):
        await bearer(auth, tenant, conn, JAMES)
    found = await store.get(tenant, conn)
    assert found is not None and found["status"] == "healthy"
    assert await store.token(tenant, conn, "test", JAMES.sub) is None
    assert await bearer(auth, tenant, conn, MAYA) == "Bearer at-maya"


class System:
    """The connected system's sign-in: answers a code with a token that names no scopes, and records token requests
    and revocations."""

    def __init__(self) -> None:
        self.revoked: list[dict[str, str]] = []
        self.asked: list[dict[str, str]] = []

    def client(self) -> httpx.AsyncClient:
        async def answer(request: httpx.Request) -> httpx.Response:
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if request.url.path == "/token":
                self.asked.append(form)
            if request.url.path == "/revoke":
                self.revoked.append(form)
                return httpx.Response(200)
            code = form.get("code", "x")
            return httpx.Response(200, json={"access_token": f"at-{code}", "refresh_token": f"rt-{code}"})

        return httpx.AsyncClient(transport=httpx.MockTransport(answer))


@pytest.fixture
def system() -> System:
    return System()


@pytest.fixture
async def client(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]], system: System
) -> AsyncIterator[httpx.AsyncClient]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    settings = Settings()
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes),
    )
    app = build_app(engine, seed, tenant, auth=auth, upstream=system.client())
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        yield c


async def personal_connection(
    client: httpx.AsyncClient, tenant: str, settings: dict[str, str] = SETTINGS, name: str = "CRM"
) -> str:
    admin = person(tenant, "Priya Shah", {TEAM: "admin"})
    security = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    await client.post("/v1/egress/hosts", json={"value": "login.bank.test"}, headers=security)
    made = await client.post(
        "/v1/connections", json={"name": name, "authKind": "oauth2_auth_code", "signIn": "person"}, headers=admin
    )
    assert made.status_code == 201 and made.json()["data"]["signIn"] == "person", made.text
    conn = made.json()["data"]["id"]
    put = await client.put(
        f"/v1/connections/{conn}/environments/test", json={"revision": 1, "settings": settings}, headers=admin
    )
    assert put.status_code == 200, put.text
    return str(conn)


async def test_a_connect_link_opens_only_for_its_person_once_and_never_for_anyone_else(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    conn = await personal_connection(client, tenant)
    store = ConnectionStore(engine)
    james = ActingForPerson(sub="usr_james", email="james@bank.example", name="James", team_id=TEAM)
    made = await ConnectLinks(store, CONSOLE_URL).make(
        tenant_id=tenant,
        connection_id=conn,
        environment="test",
        team_id=TEAM,
        person=james,
        scopes=["cases.write"],
        reason="not_connected",
    )
    link = parse_qs(urlsplit(made["connectUrl"]).query)["link"][0]
    path, body = "/v1/connections/connect-links/sign-in", {"link": link}
    maya = person(tenant, "Maya Okafor", {TEAM: "builder"})
    stolen = await client.post(path, json=body, headers=maya)
    assert stolen.status_code == 404 and stolen.json()["error"]["code"] == "connect_link_not_yours", stolen.text
    mine = await client.post(path, json=body, headers=person(tenant, "James Richardson", {TEAM: "builder"}))
    assert mine.status_code == 200, mine.text
    authorize = str(mine.json()["data"]["authorizeUrl"])
    query = {k: v[0] for k, v in parse_qs(urlsplit(authorize).query).items()}
    assert query["login_hint"] == "james@bank.example" and query["scope"] == "openid api cases.write", query
    again = await client.post(path, json=body, headers=person(tenant, "James Richardson", {TEAM: "builder"}))
    assert again.status_code == 400 and again.json()["error"]["code"] == "connect_link_expired", again.text


async def test_an_expired_connect_link_starts_nothing(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    conn = await personal_connection(client, tenant)
    store = ConnectionStore(engine)
    past = datetime.now(UTC) - timedelta(minutes=16)
    made = await ConnectLinks(store, CONSOLE_URL, clock=lambda: past).make(
        tenant_id=tenant, connection_id=conn, environment="test", team_id=TEAM, person=JAMES, scopes=[], reason="x"
    )
    link = parse_qs(urlsplit(made["connectUrl"]).query)["link"][0]
    r = await client.post(
        "/v1/connections/connect-links/sign-in",
        json={"link": link},
        headers=person(tenant, "James Richardson", {TEAM: "builder"}),
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "connect_link_expired", r.text


async def test_a_builder_starts_their_own_sign_in_but_not_the_teams(client: httpx.AsyncClient, tenant: str) -> None:
    conn = await personal_connection(client, tenant)
    builder = person(tenant, "James Richardson", {TEAM: "builder"})
    own = await client.post(f"/v1/connections/{conn}/sign-in", json={"environment": "test"}, headers=builder)
    assert own.status_code == 200, own.text
    team = await client.post(
        f"/v1/connections/{conn}/sign-in", json={"environment": "test", "account": "team"}, headers=builder
    )
    assert team.status_code == 403, team.text


def link_scopes(store: ConnectionStore, tenant: str, e: AuthFailed) -> Any:
    link = parse_qs(urlsplit(str(e.details["connectUrl"])).query)["link"][0]
    return store.link(tenant, hashlib.sha256(link.encode()).hexdigest())


async def test_an_operations_scopes_are_asked_for_up_front_and_a_token_lacking_one_asks_again_for_the_union(
    engine: AsyncEngine, tenant: str
) -> None:
    store, tokens, auth = rig(engine)
    conn = await connection(store, tenant, "person")
    with pytest.raises(AuthFailed) as first:
        await bearer(auth, tenant, conn, MAYA, ("cases.write",))
    assert first.value.details["reason"] == "not_connected"
    asked = await link_scopes(store, tenant, first.value)
    assert asked is not None and asked["scopes"] == "openid api cases.write", asked
    granted = {"access_token": "at-james", "expires_in": 3600, "scope": "openid api refresh_token"}
    await tokens.store_answer(tenant, conn, "test", granted, JAMES.sub)
    with pytest.raises(AuthFailed) as short:
        await bearer(auth, tenant, conn, JAMES, ("cases.write",))
    assert short.value.code == "CONNECTION_NOT_LINKED" and short.value.details["reason"] == "insufficient_scope"
    again = await link_scopes(store, tenant, short.value)
    assert again is not None and again["scopes"] == "openid api refresh_token cases.write", again
    assert await bearer(auth, tenant, conn, JAMES) == "Bearer at-james"
    wide = {**granted, "scope": "openid api cases.write"}
    await tokens.store_answer(tenant, conn, "test", wide, JAMES.sub)
    assert await bearer(auth, tenant, conn, JAMES, ("cases.write",)) == "Bearer at-james"


def jwt(claims: dict[str, Any]) -> str:
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"e30.{body}.sig"


async def test_granted_scopes_fall_back_to_the_tokens_claim_then_the_request_and_a_refresh_keeps_them(
    engine: AsyncEngine, tenant: str
) -> None:
    async def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "at-new", "expires_in": 3600})

    store, tokens, _ = rig(engine, httpx.AsyncClient(transport=httpx.MockTransport(answer)))
    conn = await connection(store, tenant, "person")
    claimed = {"access_token": jwt({"scp": ["api", "cases.write"]}), "expires_in": 3600}
    await tokens.store_answer(tenant, conn, "test", claimed, JAMES.sub, requested=["openid"])
    found = await store.token(tenant, conn, "test", JAMES.sub)
    assert found is not None and found["scopes"] == ["api", "cases.write"], found
    spent = {"access_token": "at-old", "refresh_token": "rt-old", "expires_in": 1}
    await tokens.store_answer(tenant, conn, "test", spent, MAYA.sub, requested=["openid", "api"])
    found = await store.token(tenant, conn, "test", MAYA.sub)
    assert found is not None and found["scopes"] == ["openid", "api"], found
    await tokens.access(tenant, conn, "test", SETTINGS, None, grant="none", person=MAYA.sub)
    found = await store.token(tenant, conn, "test", MAYA.sub)
    assert found is not None and found["rotations"] == 2 and found["scopes"] == ["openid", "api"], found


async def sign_in(
    client: httpx.AsyncClient, tenant: str, conn: str, who: tuple[str, dict[str, str]], code: str
) -> None:
    headers = person(tenant, *who)
    started = await client.post(f"/v1/connections/{conn}/sign-in", json={"environment": "test"}, headers=headers)
    assert started.status_code == 200, started.text
    state = parse_qs(urlsplit(str(started.json()["data"]["authorizeUrl"])).query)["state"][0]
    done = await client.post(
        f"/v1/connections/{conn}/sign-in/complete", json={"state": state, "code": code}, headers=headers
    )
    assert done.status_code == 200, done.text


JAMES_P = ("James Richardson", {TEAM: "builder"})
MAYA_P = ("Maya Okafor", {TEAM: "builder"})


async def test_a_sign_in_whose_answer_names_no_scopes_is_granted_what_it_asked_for(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    conn = await personal_connection(client, tenant)
    await sign_in(client, tenant, conn, JAMES_P, "james")
    rows = await ConnectionStore(engine).people(tenant, conn)
    assert [r["scopes"] for r in rows] == [["openid", "api"]], rows


async def test_a_person_lists_only_their_own_sign_ins(client: httpx.AsyncClient, tenant: str) -> None:
    conn = await personal_connection(client, tenant)
    await sign_in(client, tenant, conn, JAMES_P, "james")
    await sign_in(client, tenant, conn, MAYA_P, "maya")
    mine = await client.get("/v1/me/connections", headers=person(tenant, *JAMES_P))
    assert mine.status_code == 200, mine.text
    rows = mine.json()["data"]
    assert [(r["connectionId"], r["connection"], r["environment"]) for r in rows] == [(conn, "CRM", "test")], rows
    assert rows[0]["scopes"] == ["openid", "api"]


async def test_disconnect_deletes_only_the_persons_sign_in_and_revokes_it_at_the_system(
    client: httpx.AsyncClient, tenant: str, system: System
) -> None:
    revoking = {**SETTINGS, "revokeUrl": "https://login.bank.test/revoke"}
    conn = await personal_connection(client, tenant, revoking)
    await sign_in(client, tenant, conn, JAMES_P, "james")
    await sign_in(client, tenant, conn, MAYA_P, "maya")
    path, env = f"/v1/me/connections/{conn}", {"environment": "test"}
    gone = await client.delete(path, params=env, headers=person(tenant, *JAMES_P))
    assert gone.status_code == 204, gone.text
    assert [(r["token"], r.get("token_type_hint")) for r in system.revoked] == [("rt-james", "refresh_token")]
    assert (await client.get("/v1/me/connections", headers=person(tenant, *JAMES_P))).json()["data"] == []
    left = (await client.get("/v1/me/connections", headers=person(tenant, *MAYA_P))).json()["data"]
    assert [r["connectionId"] for r in left] == [conn], left
    twice = await client.delete(path, params=env, headers=person(tenant, *JAMES_P))
    assert twice.status_code == 404, twice.text


async def test_the_team_accounts_sign_in_asks_for_every_scope_its_operations_need_and_a_persons_does_not(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    """The team account signs calls nobody can be asked for, so it must hold its operations' scopes up front; a
    person's own sign-in from the connection asks for the connection's only and is asked again when an operation needs
    more."""
    conn = await personal_connection(client, tenant)
    store = ModuleStore(engine)
    m = await store.get_any(tenant, "mod_core_banking")
    assert m is not None
    m["connection_id"] = conn
    for o in m["operations"]:
        o["scopes"] = ["cases.write"] if o["name"] == "update_address" else []
    await store.put(m, expected_revision=m["revision"])

    def scope(r: httpx.Response) -> str:
        assert r.status_code == 200, r.text
        return parse_qs(urlsplit(str(r.json()["data"]["authorizeUrl"])).query)["scope"][0]

    path = f"/v1/connections/{conn}/sign-in"
    team = await client.post(
        path, json={"environment": "test", "account": "team"}, headers=person(tenant, "Priya Shah", {TEAM: "admin"})
    )
    assert scope(team) == "openid api cases.write"
    own = await client.post(path, json={"environment": "test"}, headers=person(tenant, *JAMES_P))
    assert scope(own) == "openid api"
