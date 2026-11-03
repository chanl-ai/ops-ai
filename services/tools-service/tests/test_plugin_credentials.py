"""A plugin's OAuth app through the real routes (c-565), by failure mode: a team with no app of its own cannot sign in
although the install set one up; Ops AI's app wins over a team's own; Ops AI's secret is copied into a team or shown
back by any read; a team's own client is kept in more than one place; and a team points its connection at Ops AI's app
by hand.

Ops AI's app is the install config's (plugin_clients), never a team's secret, so one team's secrets never serve
another team's sign-in. A team's own client lives only in app_credentials."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_plugin_sdk.loader import Loaded
from ops_service_kit.settings import PluginClient, Settings
from ops_tools.auth import Authenticator
from ops_tools.auth.tokens import Tokens
from ops_tools.connections.connect_links import ConnectLinks
from ops_tools.connections.service import ConnectionService
from ops_tools.modules.directory import Directory
from ops_tools.modules.seed import load
from ops_tools.plugins.host import PluginHost
from ops_tools.plugins.routes import plugins_router
from ops_tools.plugins.switches import InstallSwitches
from ops_tools.secrets import SecretResolver
from ops_tools.store.connections import ConnectionStore, app_credentials, connection_environments
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings
from ops_tools.store.secrets import SecretStore

from .conftest import CONSOLE_URL, build_app, credentials, response_checker
from .plugin_desk import plugin as desk
from .test_personal_sign_in import SETTINGS, AnyUrl, module
from .test_plugins import ID, Policy
from .test_review_decisions import introspect, jwks, person

TEAM = "team_platform"
SECRET = "platform-app-secret-7f3a"
TEAM_SECRET = "team-app-secret-91c2"
INSTALL = {ID: PluginClient(id="platform-client-id", secret=SecretStr(SECRET))}
Rig = tuple[httpx.AsyncClient, ConnectionService, ConnectionStore]


@pytest.fixture
async def rig(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Rig]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    settings = Settings()
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes),
    )
    app = build_app(engine, seed, tenant, auth=auth, install_clients=INSTALL)
    vault = credentials()
    store = ConnectionStore(engine, INSTALL)
    directory = Directory.from_seed(seed, datetime.now(UTC))
    connections = ConnectionService(
        store, SecretResolver(SecretStore(engine), vault),
        vault, Tokens(store, vault, None, None), directory, egress=None,
        console_url=CONSOLE_URL,
    )  # fmt: skip
    policy = {ID: {"enabled": True}}
    host = PluginHost(
        ModuleStore(engine),
        PluginBindings(engine),
        InstallSwitches(Policy(policy)),
        [Loaded("desk", desk, None)],
        store,
    )
    app.include_router(plugins_router(host, connections, directory))
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        yield c, connections, store


def team_admin(tenant: str) -> dict[str, str]:
    return person(tenant, "Priya Shah", {TEAM: "admin"})


def account_admin(tenant: str) -> dict[str, str]:
    return person(tenant, "Sam Adeyemi", {"team_security": "admin"})


async def _env(connections: ConnectionService, tenant: str, connection_id: str) -> dict[str, Any]:
    conn = await connections.store.get(tenant, connection_id)
    assert conn is not None
    return dict(conn["environments"]["production"])


async def test_a_team_with_no_app_of_its_own_signs_in_with_the_platforms(rig: Rig, tenant: str) -> None:
    client, connections, _ = rig
    on = await client.put(f"/v1/plugins/{ID}/team", json={"enabled": True}, headers=team_admin(tenant))
    assert on.status_code == 200, on.text
    conn_id = on.json()["data"]["connectionId"]
    env = await _env(connections, tenant, conn_id)
    assert env["settings"]["clientId"] == "platform-client-id" and env["platform_app"] == ID
    assert not env.get("secrets"), env  # no copy of the platform's secret in the team
    conn = await connections.store.get(tenant, conn_id)
    assert conn is not None
    proof = await connections._client_proof(  # pyright: ignore[reportPrivateUsage]
        _caller(tenant), conn, env, "sign-in Desk"
    )
    assert proof.secret == SECRET


async def test_a_teams_own_app_wins_over_the_platforms(rig: Rig, tenant: str) -> None:
    client, connections, _ = rig
    own = {"enabled": True, "clientId": "team-client-id", "clientSecret": TEAM_SECRET}
    on = await client.put(f"/v1/plugins/{ID}/team", json=own, headers=team_admin(tenant))
    assert on.status_code == 200, on.text
    env = await _env(connections, tenant, on.json()["data"]["connectionId"])
    assert env["settings"]["clientId"] == "team-client-id" and env["platform_app"] is None
    assert "clientSecret" in (env.get("secrets") or {})


async def test_edit_keys_on_a_platform_app_connection_keeps_the_platforms_app(rig: Rig, tenant: str) -> None:
    """The connection page's Edit keys sends back the kind's fields it shows, as the dialog does (c-580): the app the
    environment signs in with is not one of them, so a save that rewrites the settings must not drop it."""
    client, connections, _ = rig
    on = await client.put(f"/v1/plugins/{ID}/team", json={"enabled": True}, headers=team_admin(tenant))
    conn_id = on.json()["data"]["connectionId"]
    kinds = (await client.get("/v1/connection-kinds", headers=team_admin(tenant))).json()["data"]
    kind = next(k for k in kinds["kinds"] if k["id"] == "oauth2_auth_code")
    shown = {f["name"] for f in [*kinds["common"], *kind["fields"], *kinds["certificate"]]}
    detail = (await client.get(f"/v1/connections/{conn_id}", headers=team_admin(tenant))).json()["data"]
    settings = {k: v for k, v in detail["environments"]["production"]["settings"].items() if k in shown}
    body = {"revision": detail["revision"], "settings": {**settings, "testPath": "/api/v1/limits"}, "secretValues": {}}
    saved = await client.put(
        f"/v1/connections/{conn_id}/environments/production", json=body, headers=team_admin(tenant)
    )
    assert saved.status_code == 200, saved.text
    conn = await connections.store.get(tenant, conn_id)
    assert conn is not None
    env = dict(conn["environments"]["production"])
    proof = await connections._client_proof(_caller(tenant), conn, env, "sign-in Desk")  # pyright: ignore[reportPrivateUsage]
    assert proof.secret == SECRET, "Edit keys dropped the platform's app: the sign-in has no client secret"


async def test_ops_ais_secret_is_set_only_by_the_install_and_no_read_shows_it(rig: Rig, tenant: str) -> None:
    client, _, _ = rig
    gone = await client.put(
        f"/v1/plugins/{ID}/app-secret", json={"clientSecret": "other"}, headers=account_admin(tenant)
    )
    assert gone.status_code in (404, 405), "Ops AI's secret is the install's; no route sets it"
    listed = await client.get("/v1/plugins", headers=team_admin(tenant))
    view = next(p for p in listed.json()["data"]["plugins"] if p["id"] == ID)
    assert view["platformApp"] == {"clientId": "platform-client-id", "secretSet": True}
    on = await client.put(f"/v1/plugins/{ID}/team", json={"enabled": True}, headers=team_admin(tenant))
    conn_id = on.json()["data"]["connectionId"]
    reads = [
        listed,
        on,
        await client.get("/v1/plugins", headers=account_admin(tenant)),
        await client.get(f"/v1/connections/{conn_id}", headers=team_admin(tenant)),
        await client.get("/v1/connections", headers=team_admin(tenant)),
        await client.get("/v1/secrets", headers=team_admin(tenant)),
    ]
    assert all(SECRET not in r.text for r in reads), [r.request.url.path for r in reads if SECRET in r.text]


async def test_a_teams_own_client_is_kept_once_in_app_credentials(rig: Rig, engine: AsyncEngine, tenant: str) -> None:
    client, _, _ = rig
    own = {"enabled": True, "clientId": "team-client-id", "clientSecret": TEAM_SECRET}
    on = await client.put(f"/v1/plugins/{ID}/team", json=own, headers=team_admin(tenant))
    assert on.status_code == 200, on.text
    conn_id = on.json()["data"]["connectionId"]
    e = connection_environments
    async with engine.connect() as c:
        envs = (
            await c.execute(
                sa.select(e.c.settings, e.c.secrets, e.c.credential_id).where(
                    e.c.tenant_id == tenant, e.c.connection_id == conn_id
                )
            )
        ).all()
        creds = (
            (await c.execute(sa.select(app_credentials).where(app_credentials.c.tenant_id == tenant))).mappings().all()
        )
    assert [r["client_id"] for r in creds] == ["team-client-id"], creds
    for settings, secrets, credential_id in envs:
        assert "clientId" not in (settings or {}) and "clientSecret" not in (secrets or {}), (settings, secrets)
        assert credential_id == creds[0]["id"]


async def test_a_team_cannot_point_its_connection_at_the_platforms_app(rig: Rig, tenant: str) -> None:
    client, _, _ = rig
    made = await client.post(
        "/v1/connections", json={"name": "Desk", "authKind": "oauth2_auth_code"}, headers=team_admin(tenant)
    )
    conn = made.json()["data"]
    body = {
        "revision": conn["revision"],
        "settings": {"baseUrl": "https://acme.my.desk.test", "clientId": "x", "platformApp": ID},
        "secretValues": {"clientSecret": "s"},
    }
    put = await client.put(
        f"/v1/connections/{conn['id']}/environments/production", json=body, headers=team_admin(tenant)
    )
    assert put.status_code == 400 and "platformApp" in put.text, put.text


def _caller(tenant: str) -> Any:
    """The caller a sign-in completes for: only its tenant is read by the platform secret's lookup."""

    class Who:
        tenant_id = tenant
        name = "Priya Shah"

    return Who()


async def test_a_call_on_ops_ais_app_reads_its_secret_from_the_install_not_a_team(
    engine: AsyncEngine, tenant: str
) -> None:
    # A call refreshes an expired token with the app's secret: on Ops AI's app that secret is the install's, so
    # the connection holds no secret of its own and the token endpoint still gets the right one.
    heard: list[str | None] = []

    def token_endpoint(request: httpx.Request) -> httpx.Response:
        heard.append(parse_qs(request.content.decode()).get("client_secret", [None])[0])
        return httpx.Response(200, json={"access_token": "at-new", "expires_in": 3600, "refresh_token": "rt-2"})

    store = ConnectionStore(engine, INSTALL)
    vault = credentials()
    now = datetime.now(UTC)
    row = {
        "tenant_id": tenant, "id": "con_desk", "team_id": TEAM, "name": "Desk", "auth_kind": "oauth2_auth_code",
        "sign_in": "team", "team_backup": False, "status": "healthy", "revision": 1,
        "created_by": "t", "created_at": now, "updated_by": "t", "updated_at": now,
    }  # fmt: skip
    assert await store.create(row, actor="t", at=now)
    env = dict(SETTINGS)
    await store.change(
        tenant, "con_desk", 1, {}, actor="t", at=now, environment=("test", env, {}, {"platform_app": ID})
    )
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(token_endpoint))
    tokens = Tokens(store, vault, upstream, AnyUrl())  # pyright: ignore[reportArgumentType]
    expired = {"access_token": "at-old", "expires_in": -60, "refresh_token": "rt-1"}
    await tokens.store_answer(tenant, "con_desk", "test", expired)
    auth = Authenticator(store, None, tokens, ConnectLinks(store, CONSOLE_URL))
    prepared = await auth.prepare(module(tenant, "con_desk"), "test", tool="desk_get_case", actor="t")
    assert prepared is not None and prepared.headers["Authorization"] == "Bearer at-new"
    assert heard == [SECRET], heard
    assert SECRET in prepared.values  # redacted from anything the call logs
