"""The install's own OAuth client for a plugin, from the install config (OPS_PLUGIN_CLIENTS), through the real routes,
by failure mode: an install that set its client still shows empty client fields and makes each team bring its own; the
install's client replaces one an account admin saved; the app card claims a managed client the install does not have;
and an installed plugin stays off until someone finds the switch, or turns on when the policy cannot be read."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity, ServiceAuth, ServiceUnreachable, service_verifiers
from ops_plugin_sdk.loader import Loaded
from ops_service_kit.settings import PluginClient, Settings
from ops_tools.auth.tokens import Tokens
from ops_tools.connections.service import ConnectionService
from ops_tools.modules.directory import Directory
from ops_tools.modules.seed import load
from ops_tools.plugins.host import PluginHost
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
from .test_plugin_credentials import _caller, account_admin, team_admin  # pyright: ignore[reportPrivateUsage]
from .test_plugins import ID, Policy
from .test_review_decisions import introspect, jwks

INSTALL = {ID: PluginClient(id="install-client-id", secret=SecretStr("install-secret-5d1e"))}

Rig = tuple[httpx.AsyncClient, ConnectionService, PluginAppKeys]


def _rig(policy: dict[str, Any], install: dict[str, PluginClient]):
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
        app = build_app(engine, seed, tenant, auth=auth)
        vault = credentials()
        keys = PluginAppKeys(engine, vault, install=install)
        store = ConnectionStore(engine)
        directory = Directory.from_seed(seed, datetime.now(UTC))
        connections = ConnectionService(
            store, SecretResolver(SecretStore(engine), vault),
            vault, Tokens(store, vault, None, None), directory, egress=None,
            console_url=CONSOLE_URL, app_secret=keys.value,
        )  # fmt: skip
        switches = InstallSwitches(Policy(policy), clients=install)
        host = PluginHost(ModuleStore(engine), PluginBindings(engine), switches, [Loaded("desk", desk, None)], store)
        app.include_router(plugins_router(host, connections, directory, keys))
        app.include_router(systems_router(Systems(connections, ModuleStore(engine), host, keys), directory))
        hooks = {"response": [response_checker(app)]}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
        ) as c:
            yield c, connections, keys

    return made


# The policy never mentions the plugin: installed means on, and the install's client is the managed one.
installed = _rig({}, INSTALL)
bare = _rig({}, {})


async def _card(client: httpx.AsyncClient, tenant: str) -> dict[str, Any]:
    got = await client.get("/v1/systems", headers=team_admin(tenant))
    assert got.status_code == 200, got.text
    return next(c for c in got.json()["data"] if c["kind"] == "plugin")


async def test_an_install_client_signs_a_team_in_with_no_fields_and_no_admin_step(installed: Rig, tenant: str) -> None:
    client, connections, _ = installed
    card = await _card(client, tenant)
    assert card["managedClient"] is True and card["plugin"]["platformApp"] is True, card
    listed = await client.get("/v1/plugins", headers=team_admin(tenant))
    view = next(p for p in listed.json()["data"]["plugins"] if p["id"] == ID)
    assert view["platformApp"] == {"clientId": "install-client-id", "secretSet": True}
    on = await client.put(f"/v1/plugins/{ID}/team", json={"enabled": True}, headers=team_admin(tenant))
    assert on.status_code == 200, on.text
    conn = await connections.store.get(tenant, on.json()["data"]["connectionId"])
    assert conn is not None
    env = dict(conn["environments"]["production"])
    assert env["settings"]["clientId"] == "install-client-id" and env["platform_app"] == ID
    assert not env.get("secrets"), "the install's secret is never copied into a team"
    proof = await connections._client_proof(_caller(tenant), conn, env, "sign-in Desk")  # pyright: ignore[reportPrivateUsage]
    assert proof.secret == "install-secret-5d1e"


async def test_an_account_admins_saved_secret_wins_over_the_install_config(installed: Rig, tenant: str) -> None:
    client, _, keys = installed
    assert await keys.value(tenant, ID) == "install-secret-5d1e"
    saved = await client.put(
        f"/v1/plugins/{ID}/app-secret", json={"clientSecret": "account-secret"}, headers=account_admin(tenant)
    )
    assert saved.status_code == 200, saved.text
    assert await keys.value(tenant, ID) == "account-secret"
    assert await keys.delete(tenant, ID)
    assert await keys.value(tenant, ID) == "install-secret-5d1e", "deleting the account's falls back to the install's"


async def test_no_install_client_means_the_card_says_so(bare: Rig, tenant: str) -> None:
    client, _, _ = bare
    card = await _card(client, tenant)
    assert card["managedClient"] is False and card["plugin"]["installOn"] is True, card


class Down:
    async def get(self, path: str, *, tenant: str) -> Any:
        raise ServiceUnreachable("platform")


class Flaky:
    """Answers once, then is unreachable."""

    def __init__(self, value: dict[str, Any]) -> None:
        self.value: dict[str, Any] | None = value

    async def get(self, path: str, *, tenant: str) -> Any:
        if self.value is None:
            raise ServiceUnreachable("platform")
        value, self.value = self.value, None
        return {"value": value}


async def test_an_installed_plugin_is_on_unless_the_policy_turns_it_off() -> None:
    assert await InstallSwitches(Policy({})).on("t", ID)
    assert await InstallSwitches(Policy({ID: {"locked": {}}})).on("t", ID)
    assert not await InstallSwitches(Policy({ID: {"enabled": False}})).on("t", ID)


async def test_a_policy_that_cannot_be_read_turns_every_plugin_off() -> None:
    assert not await InstallSwitches(Down()).on("t", ID)


async def test_a_failed_read_after_a_good_one_keeps_the_last_answer() -> None:
    clock = iter([0.0, 100.0, 100.0, 100.0])
    switches = InstallSwitches(Flaky({ID: {"enabled": False}}), clock=lambda: next(clock))
    assert not await switches.on("t", ID)
    assert not await switches.on("t", ID), "an outage never turns a stopped plugin back on"
