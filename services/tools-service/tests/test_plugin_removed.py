"""A plugin a team turned on and the install then removed, by failure mode: its card vanishes, or turns into a plain
connection the team can edit as if it still worked; its page breaks; and its tools fail with a reason that sends
people to the wrong fix."""

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
from ops_tools.modules.seed import load
from ops_tools.plugins.host import PluginHost, module_id_of
from ops_tools.plugins.routes import plugins_router
from ops_tools.plugins.switches import InstallSwitches
from ops_tools.secrets import SecretResolver
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_app_keys import PluginAppKeys
from ops_tools.store.plugin_bindings import PluginBindings
from ops_tools.store.secrets import SecretStore
from ops_tools.systems import Systems, systems_router

from .conftest import CONSOLE_URL, build_app, credentials, response_checker
from .plugin_desk import plugin as desk
from .test_plugin_credentials import team_admin
from .test_plugins import ID, Policy
from .test_review_decisions import introspect, jwks

Rig = tuple[httpx.AsyncClient, PluginHost]


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
    app = build_app(engine, seed, tenant, auth=auth)
    vault = credentials()
    keys = PluginAppKeys(engine, vault)
    store = ConnectionStore(engine)
    directory = Directory.from_seed(seed, datetime.now(UTC))
    connections = ConnectionService(
        store, SecretResolver(SecretStore(engine), vault),
        vault, Tokens(store, vault, None, None), directory, egress=None,
        console_url=CONSOLE_URL, app_secret=keys.value,
    )  # fmt: skip
    host = PluginHost(
        ModuleStore(engine), PluginBindings(engine), InstallSwitches(Policy({})), [Loaded("desk", desk, None)], store
    )
    app.include_router(plugins_router(host, connections, directory, keys))
    app.include_router(systems_router(Systems(connections, ModuleStore(engine), host, keys), directory))
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        yield c, host


async def test_a_removed_plugin_keeps_its_card_and_says_it_is_no_longer_installed(rig: Rig, tenant: str) -> None:
    client, host = rig
    on = await client.put(
        f"/v1/plugins/{ID}/team", json={"enabled": True, "clientId": "app"}, headers=team_admin(tenant)
    )
    assert on.status_code == 200, on.text
    conn_id = on.json()["data"]["connectionId"]
    host.loaded = []  # the install's plugins folder no longer holds it
    got = await client.get("/v1/systems", headers=team_admin(tenant))
    cards = got.json()["data"]
    card = next(c for c in cards if c["id"] == f"plugin:{ID}")
    assert card["appState"] == "removed" and "no longer installed" in card["appStateReason"], card
    assert card["connectionId"] == conn_id and card["name"] == "Desk"
    assert not [c for c in cards if c["kind"] == "connection" and c["connectionId"] == conn_id], "shown twice"
    page = await client.get(f"/v1/apps/plugin:{ID}", headers=team_admin(tenant))
    assert page.status_code == 200, page.text
    assert page.json()["data"]["card"]["appState"] == "removed"


async def test_a_removed_plugins_tool_refuses_with_that_reason(rig: Rig, engine: AsyncEngine, tenant: str) -> None:
    _, host = rig
    module = await ModuleStore(engine).get(tenant, module_id_of(desk.manifest))
    if module is None:
        await host.ensure(tenant, datetime.now(UTC))
        module = await ModuleStore(engine).get(tenant, module_id_of(desk.manifest))
    assert module is not None
    host.loaded = []
    seen = await host.for_call(tenant, "team_platform", module, "production")
    assert "no longer installed" in str(seen["plugin_off"]), seen
