"""The install's own OAuth client for a plugin, from the install config (OPS_PLUGIN_CLIENTS), through the real routes,
by failure mode: an install that set its client still shows empty client fields and makes each team bring its own; the
app card claims a managed client the install does not have; and an installed plugin stays off until someone finds the
switch."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_plugin_sdk.loader import Loaded
from ops_service_kit.settings import PluginClient, Settings
from ops_tools.auth.tokens import Tokens
from ops_tools.connections.service import ConnectionService
from ops_tools.modules.directory import Directory
from ops_tools.modules.seed import load
from ops_tools.plugins.host import PluginHost
from ops_tools.secrets import SecretResolver
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings
from ops_tools.store.secrets import SecretStore

from .conftest import CONSOLE_URL, build_app, credentials, response_checker
from .plugin_desk import plugin as desk
from .test_plugin_credentials import _caller, team_admin  # pyright: ignore[reportPrivateUsage]
from .test_plugins import ID
from .test_review_decisions import introspect, jwks

INSTALL = {ID: PluginClient(id="install-client-id", secret=SecretStr("install-secret-5d1e"))}

Rig = tuple[httpx.AsyncClient, ConnectionService, ConnectionStore]


def _rig(install: dict[str, PluginClient]):
    @pytest.fixture
    async def made(
        engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
    ) -> AsyncIterator[Rig]:
        await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
        settings = Settings()
        auth = Auth(
            Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
            ServiceAuth(
                audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes
            ),
        )
        vault = credentials()
        store = ConnectionStore(engine, install)
        host = PluginHost(ModuleStore(engine), PluginBindings(engine), {}, [Loaded("desk", desk, None)], store)
        app = build_app(engine, seed, tenant, auth=auth, install_clients=install, plugins=host)
        directory = Directory.from_seed(seed, datetime.now(UTC))
        connections = ConnectionService(
            store, SecretResolver(SecretStore(engine), vault),
            vault, Tokens(store, vault, None, None), directory, egress=None,
            console_url=CONSOLE_URL,
        )  # fmt: skip
        hooks = {"response": [response_checker(app)]}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
        ) as c:
            yield c, connections, store

    return made


# Installed means on, and the install's client is the managed one.
installed = _rig(INSTALL)
bare = _rig({})


async def _card(client: httpx.AsyncClient, tenant: str) -> dict[str, Any]:
    got = await client.get("/v1/apps", headers=team_admin(tenant))
    assert got.status_code == 200, got.text
    return next(c for c in got.json()["data"] if c["kind"] == "plugin")


async def test_an_install_client_signs_a_team_in_with_no_fields_and_no_admin_step(installed: Rig, tenant: str) -> None:
    client, connections, _ = installed
    card = await _card(client, tenant)
    assert card["managedClient"] is True and card["plugin"]["platformApp"] is True, card
    on = await client.put(f"/v1/apps/plugin:{ID}/team", json={"enabled": True}, headers=team_admin(tenant))
    assert on.status_code == 200, on.text
    conn = await connections.store.get(tenant, on.json()["data"]["connectionId"])
    assert conn is not None
    assert conn["settings"]["clientId"] == "install-client-id" and conn["platform_app"] == ID
    assert not conn.get("secrets"), "the install's secret is never copied into a team"
    proof = await connections._client_proof(_caller(tenant), conn, "sign-in Desk")  # pyright: ignore[reportPrivateUsage]
    assert proof.secret == "install-secret-5d1e"


async def test_no_install_client_means_the_card_says_so(bare: Rig, tenant: str) -> None:
    client, _, _ = bare
    card = await _card(client, tenant)
    assert card["managedClient"] is False and card["plugin"]["platformApp"] is False, card
