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
from ops_policy import AesGcmCipher
from ops_service_kit.settings import Settings
from ops_tools.auth.tokens import Tokens
from ops_tools.connections.service import ConnectionService
from ops_tools.modules.directory import Directory
from ops_tools.modules.seed import load
from ops_tools.plugins.host import PluginHost
from ops_tools.plugins.routes import plugins_router
from ops_tools.plugins.switches import InstallSwitches
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_app_keys import PluginAppKeys
from ops_tools.store.plugin_bindings import PluginBindings
from ops_tools.store.secrets import SecretStore
from ops_tools.systems import Systems, systems_router

from .conftest import CONSOLE_URL, build_app, response_checker
from .plugin_desk import plugin as desk
from .plugin_kinds.kinds_header_key import plugin as header_key
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
    app = build_app(engine, seed, tenant, auth=auth)
    cipher = AesGcmCipher(settings.secrets_key.get_secret_value())
    keys = PluginAppKeys(engine, cipher)
    store = ConnectionStore(engine)
    directory = Directory.from_seed(seed, datetime.now(UTC))
    connections = ConnectionService(
        store, SecretStore(engine), cipher, Tokens(store, cipher, None, None), directory, egress=None,
        console_url=CONSOLE_URL, app_secret=keys.value,
    )  # fmt: skip
    host = PluginHost(
        ModuleStore(engine),
        PluginBindings(engine),
        InstallSwitches(
            Policy(
                {ID: {"enabled": True, "client": {"id": "platform-client-id"}}, "test.header-key": {"enabled": True}}
            )
        ),
        [Loaded("desk", desk, None), Loaded("header_key", header_key, None)],
    )
    app.include_router(plugins_router(host, connections, directory, keys))
    app.include_router(systems_router(Systems(connections, ModuleStore(engine), host, keys), directory))
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
    mine = [m for m in await ModuleStore(engine).all_teams(tenant) if m["team_id"] == TEAM and not m["connection_id"]]
    assert mine, "the seed has a module of the team with no connection"
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
    assert [e["id"] for e in envs] == ["test", "production"]
    assert [e["label"] for e in envs] == ["Test", "Production"]
    assert [e["id"] for e in envs if e["production"]] == ["production"]
    made = await client.post("/v1/connections", json={"name": "Ledger", "authKind": "bearer"}, headers=admin(tenant))
    assert made.status_code == 201, made.text
    card = next(c for c in await systems(client, tenant) if c["connectionId"] == made.json()["data"]["id"])
    assert {k: v["label"] for k, v in card["environments"].items()} == {"test": "Test", "production": "Production"}


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
    assert cards[ID]["fixed"] == []
