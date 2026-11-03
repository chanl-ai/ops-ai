"""The team's systems as one list of cards (c-580), by failure mode: a module and the connection it uses show as two
cards; a plugin's connection shows beside the plugin; another team's connection reaches this team's grid; a card loses
its environments' health or its details."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_plugin_sdk.loader import Loaded
from ops_service_kit.settings import Settings
from ops_tools.auth.tokens import Tokens
from ops_tools.connections.service import ConnectionService
from ops_tools.modules.directory import Directory
from ops_tools.modules.seed import ensure_platform_tools, load
from ops_tools.plugins.host import PluginHost
from ops_tools.plugins.routes import plugins_router
from ops_tools.plugins.switches import InstallSwitches
from ops_tools.secrets import SecretResolver
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.egress import EgressStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings
from ops_tools.store.secrets import SecretStore
from ops_tools.systems import Systems, systems_router

from .conftest import CONSOLE_URL, build_app, credentials, response_checker
from .plugin_desk import plugin as desk
from .plugin_kinds.kinds_header_key import plugin as header_key
from .test_plugin_credentials import INSTALL
from .test_plugins import ID, Policy
from .test_review_decisions import introspect, jwks, person

TEAM = "team_platform"


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
    app = build_app(engine, seed, tenant, auth=auth, install_clients=INSTALL)
    vault = credentials()
    store = ConnectionStore(engine, INSTALL)
    directory = Directory.from_seed(seed, datetime.now(UTC))
    connections = ConnectionService(
        store, SecretResolver(SecretStore(engine), vault),
        vault, Tokens(store, vault, None, None), directory, egress=None,
        console_url=CONSOLE_URL,
    )  # fmt: skip
    host = PluginHost(
        ModuleStore(engine),
        PluginBindings(engine),
        InstallSwitches(Policy({ID: {"enabled": True}, "test.header-key": {"enabled": True}})),
        [Loaded("desk", desk, None), Loaded("header_key", header_key, None)],
        connections.store,
    )
    app.include_router(plugins_router(host, connections, directory))
    app.include_router(systems_router(Systems(connections, ModuleStore(engine), host), directory))
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        yield c


def admin(tenant: str, team: str = TEAM) -> dict[str, str]:
    return person(tenant, "Priya Shah", {team: "admin"})


async def systems(client: httpx.AsyncClient, tenant: str) -> list[dict[str, Any]]:
    got = await client.get("/v1/systems", headers=admin(tenant))
    assert got.status_code == 200, got.text
    return list(got.json()["data"])


async def test_a_module_and_the_connection_it_uses_are_one_card(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    # Every custom module is on a connection (c-616): one moved to another is that connection's card alone.
    mine = [m for m in await ModuleStore(engine).all_teams(tenant) if m["team_id"] == TEAM and m["connection_id"]]
    assert mine, "the seed has a module of the team on a connection"
    module = mine[0]
    made = await client.post(
        "/v1/connections",
        json={"name": "Claims core", "authKind": "bearer", "category": "Core insurance"},
        headers=admin(tenant),
    )
    conn = made.json()["data"]
    bound = await client.put(
        f"/v1/tool-modules/{module['id']}/connection", json={"connectionId": conn["id"]}, headers=admin(tenant)
    )
    assert bound.status_code == 200, bound.text
    cards = await systems(client, tenant)
    holding = [c for c in cards if module["id"] in c["moduleIds"]]
    assert len(holding) == 1, holding
    card = holding[0]
    assert (card["kind"], card["connectionId"], card["category"]) == ("connection", conn["id"], "Core insurance")
    assert card["toolsCount"] == len(module["operations"])
    assert set(card["environments"]) == {"test", "production"}


async def test_a_plugins_connection_is_part_of_the_plugins_card(client: httpx.AsyncClient, tenant: str) -> None:
    on = await client.put(f"/v1/plugins/{ID}/team", json={"enabled": True, "clientId": "app"}, headers=admin(tenant))
    conn_id = on.json()["data"]["connectionId"]
    cards = await systems(client, tenant)
    plugin = next(c for c in cards if c["kind"] == "plugin")
    assert plugin["connectionId"] == conn_id and plugin["category"] == "Service desk", plugin
    assert plugin["environments"]["production"]["set"] and not plugin["environments"]["test"]["set"]
    assert not [c for c in cards if c["kind"] == "connection" and c["connectionId"] == conn_id], "shown twice"


async def test_another_teams_connection_never_reaches_this_teams_grid(client: httpx.AsyncClient, tenant: str) -> None:
    theirs = await client.post(
        "/v1/connections", json={"name": "Ops ledger", "authKind": "api_key"}, headers=admin(tenant, "team_ops")
    )
    assert theirs.status_code == 201, theirs.text
    cards = await systems(client, tenant)
    assert theirs.json()["data"]["id"] not in {c["connectionId"] for c in cards}


async def test_the_environments_come_from_the_service_with_their_names_and_which_is_production(
    client: httpx.AsyncClient, tenant: str
) -> None:
    """The console draws each environment from these, so a team-defined environment is data, not console code."""
    kinds = (await client.get("/v1/connection-kinds", headers=admin(tenant))).json()["data"]
    envs = kinds["environments"]
    assert [(e["id"], e["label"], e["keys"], e["production"]) for e in envs] == [
        ("dev", "Dev", False, False),
        ("test", "Test", True, False),
        ("production", "Production", True, True),
    ]
    made = await client.post("/v1/connections", json={"name": "Ledger", "authKind": "bearer"}, headers=admin(tenant))
    assert made.status_code == 201, made.text
    card = next(c for c in await systems(client, tenant) if c["connectionId"] == made.json()["data"]["id"])
    assert {k: v["label"] for k, v in card["environments"].items()} == {"test": "Test", "production": "Production"}


async def test_every_pem_field_is_marked_so_the_dialog_never_asks_for_it_on_one_line(
    client: httpx.AsyncClient, tenant: str
) -> None:
    """A certificate or key pasted into a one-line box loses its line breaks and no longer reads (c-580 PM test)."""
    kinds = (await client.get("/v1/connection-kinds", headers=admin(tenant))).json()["data"]
    fields = [*kinds["certificate"], *(f for k in kinds["kinds"] for f in k["fields"])]
    pem = {f["name"] for f in fields if f.get("pem")}
    assert pem == {"clientCertificate", "clientKey", "trustedCa", "signingCertificate", "signingKey"}, pem


async def test_a_plugins_card_says_how_it_signs_in_and_which_settings_a_team_types(
    client: httpx.AsyncClient, tenant: str
) -> None:
    """The connect dialog builds a plugin's form from its card: a setting read from the token is never typed, and one
    each environment keeps its own is asked per environment."""
    cards = await systems(client, tenant)
    plugin = next(c for c in cards if c["kind"] == "plugin")["plugin"]
    assert plugin["kinds"] == ["oauth2_auth_code"] and plugin["signIn"] == ["team"], plugin
    assert plugin["scopes"] == ["Read and change records"]
    typed = [(s["name"], s["perEnvironment"]) for s in plugin["settings"]]
    assert typed == [("api_version", False)], plugin["settings"]
    assert plugin["settings"][0]["default"] == "1"


async def test_a_field_the_plugin_fixes_is_never_asked_so_a_team_cannot_send_it_elsewhere(
    client: httpx.AsyncClient, tenant: str
) -> None:
    """A plugin that names its key's header fixes it; a team typing another name would send the key under that one."""
    cards = {c["pluginId"]: c["plugin"] for c in await systems(client, tenant) if c["kind"] == "plugin"}
    assert cards["test.header-key"]["fixed"] == ["name", "placement"], cards["test.header-key"]
    # A plugin that names its sign-in addresses and permissions fixes them too: a typed token address would send the
    # client secret to another host (c-580 PM test, "Token address" asked though the plugin sets it).
    assert cards[ID]["fixed"] == ["authorizeUrl", "scopes", "tokenUrl"], cards[ID]


async def test_an_apps_page_is_one_answer_with_its_card_connection_tools_and_who_is_signed_in(
    client: httpx.AsyncClient, tenant: str
) -> None:
    """The app's page (c-607) shows its accounts, tools, skills, usage and settings from one answer, so the console
    never joins the systems, connection, module and plugin lists itself; another team's app is not found."""
    on = await client.put(f"/v1/plugins/{ID}/team", json={"enabled": True, "clientId": "app"}, headers=admin(tenant))
    assert on.status_code == 200, on.text
    got = await client.get(f"/v1/apps/plugin:{ID}", headers=admin(tenant))
    assert got.status_code == 200, got.text
    page = got.json()["data"]
    assert page["card"]["id"] == f"plugin:{ID}" and page["connection"]["id"] == on.json()["data"]["connectionId"]
    assert [t["name"] for t in page["tools"]] == [t["name"] for t in page["tools"]] and len(page["tools"]) == len(
        desk.manifest.tools
    )
    assert all(t["title"] and t["access"] in ("read", "write") for t in page["tools"]), page["tools"]
    assert page["me"] == {"connected": False, "account": None} and page["peopleCount"] == 0, page
    assert page["usage"] == [] and page["skills"] == []
    other = await client.get(f"/v1/apps/{page['connection']['id']}", headers=admin(tenant, "team_cards"))
    assert other.status_code == 404, other.text


async def test_the_apps_grid_lists_no_built_in_app_or_connection_made_for_a_tool(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    """The Apps grid lists the plugins and the apps a person added (owner, 2026-11-01): a built-in app has its own menu
    and a connection made to hold a custom tool's address is reached from the tool, though both pages still answer."""
    await ensure_platform_tools(ModuleStore(engine), tenant_id=tenant, at=datetime.now(UTC), team_id=TEAM)
    tool = {
        "name": "read_rate", "description": "Reads a rate.", "access": "read", "method": "GET",
        "url": "https://rates.test/v1/rates/{currency}",
    }  # fmt: skip
    await EgressStore(engine).add(tenant, "host", "rates.test", actor="test", note="", at=datetime.now(UTC))
    body = {"name": "rates", "displayName": "Rates", "system": "Rates", "http": tool}
    made = await client.post("/v1/tool-modules", json=body, headers=admin(tenant))
    assert made.status_code == 201, made.text
    own = made.json()["data"]["connection"]["id"]
    added = await client.post("/v1/connections", json={"name": "Ledger", "authKind": "none"}, headers=admin(tenant))
    person_made = added.json()["data"]["id"]
    listed = {c["id"]: c for c in await systems(client, tenant)}
    assert not [c for c in listed.values() if c["kind"] in ("builtin", "module")], sorted(listed)
    assert own not in listed and person_made in listed, sorted(listed)
    mail = (await client.get("/v1/apps/builtin:mailboxes", headers=admin(tenant))).json()["data"]
    assert {t["name"] for t in mail["tools"]} <= {"send_reply", "send_acknowledgement"} and mail["connection"] is None
    tool_app = await client.get(f"/v1/apps/{own}", headers=admin(tenant))
    assert tool_app.status_code == 200 and tool_app.json()["data"]["tools"][0]["name"] == "read_rate", tool_app.text


# ── An app reads Connected only after a sign-in or a passing test (c-616) ──


async def _turned_on(client: httpx.AsyncClient, tenant: str) -> str:
    on = await client.put(f"/v1/plugins/{ID}/team", json={"enabled": True, "clientId": "app"}, headers=admin(tenant))
    assert on.status_code == 200, on.text
    return str(on.json()["data"]["connectionId"])


async def _app(client: httpx.AsyncClient, tenant: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The plugin's card in the grid and the default account on its page."""
    card = next(c for c in await systems(client, tenant) if c["id"] == f"plugin:{ID}")
    page = (await client.get(f"/v1/apps/plugin:{ID}", headers=admin(tenant))).json()["data"]
    return card, page["accounts"][0]


def _token(**extra: Any) -> dict[str, Any]:
    return {"access_ct": "ct", "scopes": [], "rotations": 0, "refreshed_at": datetime.now(UTC), **extra}


async def test_an_app_turned_on_reads_not_signed_in_until_the_team_account_signs_in(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    conn = await _turned_on(client, tenant)
    card, account = await _app(client, tenant)
    assert (card["state"], card["status"]) == ("not_signed_in", "draft"), card
    assert (account["state"], account["status"]) == ("not_signed_in", "draft"), account
    await ConnectionStore(engine).replace_token(tenant, conn, "production", _token())
    card, account = await _app(client, tenant)
    assert (card["state"], card["status"]) == ("connected", "healthy"), card
    assert account["state"] == "connected", account


async def test_a_refused_or_expired_team_account_reads_so(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    conn = await _turned_on(client, tenant)
    store = ConnectionStore(engine)
    past = datetime(2026, 1, 1, tzinfo=UTC)
    await store.replace_token(tenant, conn, "production", _token(expires_at=past))
    card, _ = await _app(client, tenant)
    assert (card["state"], card["status"]) == ("expired", "needs_reconnect"), card
    await store.replace_token(tenant, conn, "production", _token(refresh_ct="rt", expires_at=past))
    assert (await _app(client, tenant))[0]["state"] == "connected", "a token that renews itself is still connected"
    await store.mark_refused(tenant, conn, "production", "", reason="invalid_grant", at=datetime.now(UTC))
    card, account = await _app(client, tenant)
    assert (card["state"], card["status"]) == ("refused", "needs_reconnect"), card
    assert account["state"] == "refused", account


async def test_a_passing_test_with_no_token_reads_connected(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    """An API key or password signs in with no token row: Test connection passing is what shows it works."""
    conn = await _turned_on(client, tenant)
    health = {
        "environment": "production",
        "status": "ok",
        "account": "team",
        "at": "2026-11-01T00:00:00Z",
        "by": "Priya Shah",
    }
    await ConnectionStore(engine).set_health(tenant, conn, health)
    assert (await _app(client, tenant))[0]["state"] == "connected"


async def test_the_approval_pickers_list_keeps_the_built_in_apps(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    # A mailbox reply is the write a team most often approves (owner, 2026-11-01): its picker asks for the built-ins.
    await ensure_platform_tools(ModuleStore(engine), tenant_id=tenant, at=datetime.now(UTC), team_id=TEAM)
    r = await client.get("/v1/systems", params={"include": "builtin"}, headers=admin(tenant))
    assert r.status_code == 200, r.text
    assert "builtin:mailboxes" in {c["id"] for c in r.json()["data"]}, r.json()["data"]


async def test_a_team_never_provisioned_gets_its_built_in_apps_when_they_are_asked_for(
    client: httpx.AsyncClient, tenant: str
) -> None:
    # A team made before team.created reached tools-service has no defaults row, so no start-up catch-up finds it; its
    # first listing provisions it, as a first tool lookup does.
    r = await client.get("/v1/systems", params={"include": "builtin"}, headers=admin(tenant, "team_cards"))
    assert r.status_code == 200, r.text
    assert "builtin:mailboxes" in {c["id"] for c in r.json()["data"]}, r.json()["data"]
