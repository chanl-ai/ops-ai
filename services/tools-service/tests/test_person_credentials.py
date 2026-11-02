"""Each person's own key, password or token on a connection (c-595), by failure mode: a person's call carries the
team's key or another person's; a connection that signs in as each person refuses every call because the team holds no
key; a call with nobody behind it uses someone's key; a person with no key is sent to an OAuth sign-in that cannot
start; a person's key is left out of what the gateway scrubs; the call log cannot tell whose key signed the call."""

from __future__ import annotations

import base64
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast, get_args

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import ActingForPerson, Auth, Identity, ServiceAuth, service_verifiers
from ops_service_kit.settings import Settings
from ops_tools.auth import Authenticator, AuthFailed, NotLinkedReason, Prepared
from ops_tools.auth.kinds import KINDS
from ops_tools.auth.tokens import Tokens
from ops_tools.connections.connect_links import ConnectLinks
from ops_tools.executor import HttpExecutor
from ops_tools.store.connections import ConnectionStore

from .conftest import CONSOLE_URL, build_app, credentials, response_checker
from .test_plugin_sign_in import TEAM as PLUGIN_TEAM

# The plugin tests' rig, a fixture, used by name below.
from .test_plugin_sign_in import (
    Rig,
    admin,
    rig,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from .test_plugin_sign_in import turn_on as plugin_turn_on
from .test_review_decisions import introspect, jwks, person

TEAM = "team_platform"
BASE = "https://ledger.bank.test"
JAMES = ActingForPerson(sub="usr_james", email="james@bank.example", name="James", team_id=TEAM)
MAYA = ActingForPerson(sub="usr_maya", email="maya@bank.example", name="Maya", team_id=TEAM)
# What each kind takes from the team (plain settings) when each person brings the secret part.
PLAIN: dict[str, dict[str, str]] = {
    "api_key": {"baseUrl": BASE, "name": "X-Api-Key"},
    "basic": {"baseUrl": BASE},
    "bearer": {"baseUrl": BASE},
}
OWN: dict[str, dict[str, dict[str, str]]] = {
    "api_key": {JAMES.sub: {"key": "key-james"}, MAYA.sub: {"key": "key-maya"}},
    "basic": {
        JAMES.sub: {"username": "james", "password": "pw-james"},
        MAYA.sub: {"username": "maya", "password": "pw-maya"},
    },
    "bearer": {JAMES.sub: {"token": "tok-james"}, MAYA.sub: {"token": "tok-maya"}},
}


def _rig(engine: AsyncEngine) -> tuple[ConnectionStore, Tokens, Authenticator]:
    store = ConnectionStore(engine)
    tokens = Tokens(store, credentials(), None, None)  # pyright: ignore[reportArgumentType]
    return store, tokens, Authenticator(store, None, tokens, ConnectLinks(store, CONSOLE_URL))


async def _connection(store: ConnectionStore, tenant: str, kind: str, sign_in: str = "person") -> str:
    now, cid = datetime.now(UTC), f"con_{kind}_{sign_in}"
    row: dict[str, Any] = {
        "tenant_id": tenant,
        "id": cid,
        "team_id": TEAM,
        "name": "Ledger",
        "auth_kind": kind,
        "sign_in": sign_in,
        "team_backup": False,
        "status": "healthy",
        "revision": 1,
        "created_by": "t",
        "created_at": now,
        "updated_by": "t",
        "updated_at": now,
    }
    assert await store.create(row, actor="t", at=now)
    await store.change(tenant, cid, 1, {}, actor="t", at=now, environment=("test", PLAIN[kind], {}))
    return cid


async def _call(auth: Authenticator, tenant: str, conn: str, who: ActingForPerson | None) -> Prepared:
    module = {"tenant_id": tenant, "team_id": TEAM, "connection_id": conn, "endpoint": BASE}
    prepared = await auth.prepare(module, "test", tool="ledger_post", actor="t", acting_for=who)
    assert prepared is not None
    return prepared


def _signed(kind: str, p: Prepared) -> str:
    if kind == "api_key":
        return p.headers["X-Api-Key"]
    if kind == "basic":
        return base64.b64decode(p.headers["Authorization"].removeprefix("Basic ")).decode()
    return p.headers["Authorization"].removeprefix("Bearer ")


def test_key_password_and_token_kinds_take_each_persons_own_and_service_accounts_do_not() -> None:
    per_person = {k.id: k.person_fields for k in KINDS if k.per_person}
    assert per_person == {
        "api_key": ("key",),
        "basic": ("username", "password"),
        "bearer": ("token",),
        "oauth2_auth_code": (),
    }


@pytest.mark.parametrize("kind", ["api_key", "basic", "bearer"])
async def test_each_persons_call_carries_their_own_secret_and_the_log_says_person(
    engine: AsyncEngine, tenant: str, kind: str
) -> None:
    store, tokens, auth = _rig(engine)
    conn = await _connection(store, tenant, kind)
    for who, values in OWN[kind].items():
        await tokens.store_own(tenant, conn, "test", who, values)
    james, maya = await _call(auth, tenant, conn, JAMES), await _call(auth, tenant, conn, MAYA)
    expect = {"api_key": ("key-james", "key-maya"), "basic": ("james:pw-james", "maya:pw-maya")}
    assert (_signed(kind, james), _signed(kind, maya)) == expect.get(kind, ("tok-james", "tok-maya"))
    assert james.credential == "person"
    secret = next(v for f, v in OWN[kind][JAMES.sub].items() if f != "username")
    assert secret in james.values, "the person's secret is scrubbed from what the call returns"


async def test_a_person_with_no_key_gets_a_link_naming_the_fields_to_give(engine: AsyncEngine, tenant: str) -> None:
    store, tokens, auth = _rig(engine)
    conn = await _connection(store, tenant, "basic")
    await tokens.store_own(tenant, conn, "test", MAYA.sub, OWN["basic"][MAYA.sub])
    with pytest.raises(AuthFailed) as e:
        await _call(auth, tenant, conn, JAMES)
    d = e.value.details
    assert e.value.code == "CONNECTION_NOT_LINKED" and d["reason"] == "not_connected", d
    assert (d["authKind"], d["personFields"]) == ("basic", ["username", "password"])
    assert str(d["connectUrl"]).startswith(f"{CONSOLE_URL}/connections/connect?")


async def test_a_call_with_nobody_behind_it_uses_nobodys_key(engine: AsyncEngine, tenant: str) -> None:
    store, tokens, auth = _rig(engine)
    conn = await _connection(store, tenant, "api_key")
    await tokens.store_own(tenant, conn, "test", JAMES.sub, OWN["api_key"][JAMES.sub])
    with pytest.raises(AuthFailed) as e:
        await _call(auth, tenant, conn, None)
    assert e.value.code == "CONNECTION_NOT_LINKED" and e.value.details["reason"] == "no_person"


async def test_a_team_connection_still_signs_with_the_teams_key(engine: AsyncEngine, tenant: str) -> None:
    store, _, auth = _rig(engine)
    conn = await _connection(store, tenant, "bearer", sign_in="team")
    with pytest.raises(AuthFailed) as e:
        await _call(auth, tenant, conn, JAMES)
    # The team set no token: the team gate still asks the team, never the person.
    assert e.value.code == "CONNECTION_NOT_SET", e.value.code


# ── Through the routes: Your connections and Test connection ──────────────────────────────────────────────────────

LEDGER_KEYS = {"key-james": "James", "key-maya": "Maya"}
JAMES_P = ("James Richardson", {TEAM: "builder"})
MAYA_P = ("Maya Okafor", {TEAM: "builder"})


class Ledger:
    """A system that takes each person's own API key, as the real ones do: an unknown key is its 401."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def client(self) -> httpx.AsyncClient:
        async def answer(request: httpx.Request) -> httpx.Response:
            key = request.headers.get("X-Api-Key", "")
            self.seen.append(key)
            if key not in LEDGER_KEYS:
                return httpx.Response(401, json={"error": "invalid_api_key"})
            return httpx.Response(200, json={"user": LEDGER_KEYS[key]})

        return httpx.AsyncClient(transport=httpx.MockTransport(answer))


@pytest.fixture
def ledger() -> Ledger:
    return Ledger()


@pytest.fixture
async def client(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, ledger: Ledger
) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings()
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes),
    )
    app = build_app(engine, seed, tenant, auth=auth, upstream=ledger.client())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://tools",
        event_hooks={"response": [response_checker(app)]},
    ) as c:
        security = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
        await c.post("/v1/egress/hosts", json={"value": "ledger.bank.test"}, headers=security)
        yield c


async def _ledger(client: httpx.AsyncClient, tenant: str, sign_in: str = "person") -> str:
    admin = person(tenant, "Priya Shah", {TEAM: "admin"})
    made = await client.post(
        "/v1/connections", json={"name": "Ledger", "authKind": "api_key", "signIn": sign_in}, headers=admin
    )
    assert made.status_code == 201, made.text
    conn = str(made.json()["data"]["id"])
    body: dict[str, Any] = {"revision": 1, "settings": {"baseUrl": BASE, "name": "X-Api-Key", "testPath": "/me"}}
    if sign_in == "team":
        body["secretValues"] = {"key": "key-team"}
    put = await client.put(f"/v1/connections/{conn}/environments/test", json=body, headers=admin)
    # On a person connection the team sets the address and how the key is sent, and no key of its own.
    assert put.status_code == 200, put.text
    return conn


async def _give(
    client: httpx.AsyncClient, tenant: str, conn: str, who: tuple[str, dict[str, str]], **fields: str
) -> httpx.Response:
    body = {"environment": "test", "credentials": fields}
    return await client.put(f"/v1/me/connections/{conn}/credentials", json=body, headers=person(tenant, *who))


async def test_each_person_gives_their_own_key_and_tests_with_it_and_nobody_sees_it(
    client: httpx.AsyncClient, tenant: str, ledger: Ledger
) -> None:
    conn = await _ledger(client, tenant)
    given = await _give(client, tenant, conn, JAMES_P, key="key-james")
    assert given.status_code == 200, given.text
    assert given.json()["data"]["method"] == "API key" and "key-james" not in given.text
    assert (await _give(client, tenant, conn, MAYA_P, key="key-maya")).status_code == 200
    for who, key in ((JAMES_P, "key-james"), (MAYA_P, "key-maya")):
        tested = await client.post(
            f"/v1/connections/{conn}/test", json={"environment": "test"}, headers=person(tenant, *who)
        )
        assert tested.status_code == 200 and tested.json()["data"]["health"]["status"] == "ok", tested.text
        assert ledger.seen[-1] == key
    mine = await client.get("/v1/me/connections", headers=person(tenant, *JAMES_P))
    rows = mine.json()["data"]
    assert [(r["connectionId"], r["method"]) for r in rows] == [(conn, "API key")], rows
    detail = await client.get(f"/v1/connections/{conn}", headers=person(tenant, "Priya Shah", {TEAM: "admin"}))
    assert "key-james" not in detail.text and "key-maya" not in detail.text


async def test_a_wrong_key_fails_for_that_person_alone_and_disconnect_asks_again(
    client: httpx.AsyncClient, tenant: str, ledger: Ledger
) -> None:
    conn = await _ledger(client, tenant)
    await _give(client, tenant, conn, JAMES_P, key="key-wrong")
    await _give(client, tenant, conn, MAYA_P, key="key-maya")
    james = await client.post(
        f"/v1/connections/{conn}/test", json={"environment": "test"}, headers=person(tenant, *JAMES_P)
    )
    assert james.json()["data"]["health"]["status"] != "ok", james.text
    maya = await client.post(
        f"/v1/connections/{conn}/test", json={"environment": "test"}, headers=person(tenant, *MAYA_P)
    )
    assert maya.json()["data"]["health"]["status"] == "ok", maya.text
    admin = person(tenant, "Priya Shah", {TEAM: "admin"})
    assert (await client.get(f"/v1/connections/{conn}", headers=admin)).json()["data"]["status"] == "healthy"
    gone = await client.delete(
        f"/v1/me/connections/{conn}", params={"environment": "test"}, headers=person(tenant, *JAMES_P)
    )
    assert gone.status_code == 204, gone.text
    assert (await client.get("/v1/me/connections", headers=person(tenant, *JAMES_P))).json()["data"] == []


async def test_a_field_the_method_lacks_or_a_team_connection_is_refused_and_nothing_kept(
    client: httpx.AsyncClient, tenant: str
) -> None:
    conn = await _ledger(client, tenant)
    stray = await _give(client, tenant, conn, JAMES_P, key="key-james", password="x")
    assert stray.status_code == 400 and stray.json()["error"]["details"]["field"] == "password", stray.text
    empty = await _give(client, tenant, conn, JAMES_P, key=" ")
    assert empty.status_code == 400, empty.text
    team = await _ledger(client, tenant, sign_in="team")
    refused = await _give(client, tenant, team, JAMES_P, key="key-james")
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "sign_in_unsupported", refused.text
    assert (await client.get("/v1/me/connections", headers=person(tenant, *JAMES_P))).json()["data"] == []


async def test_a_plugin_turned_on_for_each_persons_key_holds_its_card_details_and_asks_the_team_for_no_key(
    rig: Rig,  # noqa: F811 (the imported fixture)
    tenant: str,
) -> None:
    on = await plugin_turn_on(rig, tenant, "test.person-key", signIn="person")
    assert on.status_code == 200, on.text
    conn = str(on.json()["data"]["connectionId"])
    detail = (await rig.client.get(f"/v1/connections/{conn}", headers=admin(tenant))).json()["data"]
    assert (detail["signIn"], detail["category"], detail["docsUrl"]) == (
        "person",
        "Service desk",
        "https://docs.multi.test/keys",
    ), detail
    given = await rig.client.put(
        f"/v1/me/connections/{conn}/credentials",
        json={"environment": "production", "credentials": {"key": "key-james"}},
        headers=person(tenant, "James Richardson", {PLUGIN_TEAM: "builder"}),
    )
    assert given.status_code == 200 and given.json()["data"]["method"] == "API key", given.text


async def test_your_connections_offers_every_app_you_can_connect_and_its_form(
    client: httpx.AsyncClient, tenant: str
) -> None:
    conn = await _ledger(client, tenant)
    await _ledger(client, tenant, sign_in="team")
    james = person(tenant, *JAMES_P)
    before = (await client.get("/v1/me/connections", params={"every": "true"}, headers=james)).json()["data"]
    assert [(r["connectionId"], r["connected"], r["personFields"]) for r in before] == [(conn, False, ["key"])], before
    assert (await client.get("/v1/me/connections", headers=james)).json()["data"] == []
    await _give(client, tenant, conn, JAMES_P, key="key-james")
    after = (await client.get("/v1/me/connections", params={"every": "true"}, headers=james)).json()["data"]
    assert [(r["connectionId"], r["connected"], r["method"]) for r in after] == [(conn, True, "API key")], after


def test_the_console_knows_every_reason_a_call_is_refused_for_a_missing_sign_in() -> None:
    """The console's card looks its text up by reason; a reason it lacks rendered nothing (no_person, c-595 review)."""
    ts = (Path(__file__).resolve().parents[3] / "apps/console/src/lib/types/connections.ts").read_text()
    found = re.search(r"CONNECTION_REQUIRED_REASONS = \[([^\]]*)\]", ts)
    assert found is not None, "lib/types/connections.ts no longer lists CONNECTION_REQUIRED_REASONS"
    assert re.findall(r"'([a-z_]+)'", found.group(1)) == list(get_args(NotLinkedReason))


# ── A refused key or sign-in is marked on the person's own row (c-595, the mock's 1g and 1h) ─────────────────────


class AllowLedger:
    async def check_url(self, tenant_id: str, url: str) -> str:
        return "ledger.bank.test"


async def test_a_call_the_system_refuses_with_a_persons_key_asks_for_it_again_and_marks_only_their_row(
    engine: AsyncEngine, tenant: str
) -> None:
    store, tokens, auth = _rig(engine)
    conn = await _connection(store, tenant, "api_key")
    await tokens.store_own(tenant, conn, "test", JAMES.sub, {"key": "key-wrong"})
    await tokens.store_own(tenant, conn, "test", MAYA.sub, OWN["api_key"][MAYA.sub])
    seen: list[str] = []

    async def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("X-Api-Key", ""))
        ok = request.headers.get("X-Api-Key") == "key-maya"
        return httpx.Response(200 if ok else 401, json={"ok": ok})

    executor = HttpExecutor(httpx.AsyncClient(transport=httpx.MockTransport(answer)), AllowLedger(), auth=auth)  # pyright: ignore[reportArgumentType]
    module: dict[str, Any] = {
        "tenant_id": tenant,
        "team_id": TEAM,
        "connection_id": conn,
        "endpoint": BASE,
        "egress_hosts": ["ledger.bank.test"],
        "timeout_ms": 8000,
    }
    op: dict[str, Any] = {
        "name": "ledger_get",
        "method": "GET",
        "path": "/entries",
        "headers": [],
        "masked_output": [],
        "access": "read",
    }
    refused = await executor.run(module, op, {}, environment="test", acting_for=JAMES)
    error = cast(dict[str, Any], refused.output)["error"]
    assert not refused.ok and error["code"] == "CONNECTION_NOT_LINKED", refused.output
    assert (error["details"]["reason"], error["details"]["personFields"]) == ("refused", ["key"]), error
    # Asked again before the system is called: the refused key is not sent twice.
    again = await executor.run(module, op, {}, environment="test", acting_for=JAMES)
    assert cast(dict[str, Any], again.output)["error"]["details"]["reason"] == "refused" and seen == ["key-wrong"]
    assert (await executor.run(module, op, {}, environment="test", acting_for=MAYA)).ok
    found = await store.get(tenant, conn)
    assert found is not None and found["status"] == "healthy"
    # A new key clears the mark.
    await tokens.store_own(tenant, conn, "test", JAMES.sub, OWN["api_key"][JAMES.sub])
    assert _signed("api_key", await _call(auth, tenant, conn, JAMES)) == "key-james"


async def test_your_connections_shows_a_refused_key_with_its_reason_and_asks_for_a_new_one(
    client: httpx.AsyncClient, tenant: str
) -> None:
    conn = await _ledger(client, tenant)
    await _give(client, tenant, conn, JAMES_P, key="key-wrong")
    tested = await client.post(
        f"/v1/connections/{conn}/test", json={"environment": "test"}, headers=person(tenant, *JAMES_P)
    )
    assert tested.json()["data"]["health"]["status"] != "ok", tested.text
    rows = (await client.get("/v1/me/connections", params={"every": "true"}, headers=person(tenant, *JAMES_P))).json()[
        "data"
    ]
    assert [(r["refused"], "401" in (r["refusedReason"] or "")) for r in rows] == [(True, True)], rows
    await _give(client, tenant, conn, JAMES_P, key="key-james")
    rows = (await client.get("/v1/me/connections", params={"every": "true"}, headers=person(tenant, *JAMES_P))).json()[
        "data"
    ]
    assert [r["refused"] for r in rows] == [False], rows
