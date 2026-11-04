"""A team keeps several named accounts of one app, by failure mode: a second account replaces the first; a
sign-in on the second account settles the first's instance; a call naming an account runs with another, or with
another team's; a person's call ignores the account they pinned; and with several_accounts off, a second account
can still be made or named."""

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
from ops_tools.modules.service import ModuleService
from ops_tools.modules.tool_users import StaticToolUsers
from ops_tools.plugins.host import PluginHost, module_id_of
from ops_tools.plugins.routes import plugins_router
from ops_tools.plugins.switches import InstallSwitches
from ops_tools.registry import ToolRegistry
from ops_tools.secrets import SecretResolver
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_app_keys import PluginAppKeys
from ops_tools.store.plugin_bindings import PluginBindings
from ops_tools.store.secrets import SecretStore
from ops_tools.systems import Systems, systems_router

from .conftest import CONSOLE_URL, build_app, credentials, response_checker
from .plugin_desk import plugin as desk
from .test_plugins import ID, Policy
from .test_review_decisions import introspect, jwks, person

TEAM = "team_platform"
OTHER = "team_cards"
TOOL = "desk_get_case"


class World:
    def __init__(
        self,
        client: httpx.AsyncClient,
        host: PluginHost,
        registry: ToolRegistry,
        store: ConnectionStore,
        users: StaticToolUsers,
    ):
        self.client, self.host, self.registry, self.store, self.users = client, host, registry, store, users


@pytest.fixture
async def world(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]], local_catalog: Any
) -> AsyncIterator[World]:
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
        ModuleStore(engine),
        PluginBindings(engine),
        InstallSwitches(Policy({ID: {"enabled": True, "client": {"id": "platform-client-id"}}})),
        [Loaded("desk", desk, None)],
        store,
        accounts=True,
    )
    users = StaticToolUsers()
    app.include_router(plugins_router(host, connections, directory, keys, users=users))
    app.include_router(systems_router(Systems(connections, ModuleStore(engine), host, keys), directory))
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        yield World(c, host, ToolRegistry(local_catalog, ModuleStore(engine), host), store, users)


def admin(tenant: str, team: str = TEAM) -> dict[str, str]:
    return person(tenant, "Priya Shah", {team: "admin"})


async def connected(w: World, tenant: str, team: str = TEAM) -> str:
    """The team's first Desk account, on with the team's own app; its connection id."""
    on = await w.client.put(
        f"/v1/plugins/{ID}/team", json={"enabled": True, "clientId": "app"}, headers=admin(tenant, team)
    )
    assert on.status_code == 200, on.text
    return str(on.json()["data"]["connectionId"])


async def another(w: World, tenant: str, name: str, team: str = TEAM) -> httpx.Response:
    body = {"name": name, "clientId": "eu-app"}
    return await w.client.post(f"/v1/plugins/{ID}/accounts", json=body, headers=admin(tenant, team))


async def signed(w: World, tenant: str, connection_id: str, instance: str, person_id: str = "") -> None:
    """A finished sign-in on the account: the instance its token named, and its token row (the team's or a person's)."""
    await w.host.on_token(tenant, connection_id, {"instance_url": instance}, "production")
    await w.store.replace_token(
        tenant,
        connection_id,
        "production",
        {"access_ct": "ct", "scopes": [], "rotations": 0, "refreshed_at": datetime.now(UTC)},
        person=person_id,
    )


async def test_a_second_named_account_is_made_beside_the_first_which_stays_the_default(
    world: World, tenant: str
) -> None:
    first = await connected(world, tenant)
    made = await another(world, tenant, "EU org")
    assert made.status_code == 201, made.text
    second = made.json()["data"]
    assert second["id"].startswith("ca_") and second["accountName"] == "EU org" and second["pluginId"] == ID
    page = (await world.client.get(f"/v1/apps/plugin:{ID}", headers=admin(tenant))).json()["data"]
    assert [(a["id"], a["name"], a["default"]) for a in page["accounts"]] == [
        (first, "Desk", True),
        (second["id"], "EU org", False),
    ]
    again = await another(world, tenant, "eu ORG")
    assert again.status_code == 409, again.text


async def test_a_sign_in_on_the_second_account_settles_its_own_instance_and_a_call_naming_it_uses_it(
    world: World, tenant: str
) -> None:
    first = await connected(world, tenant)
    second = (await another(world, tenant, "EU org")).json()["data"]["id"]
    await signed(world, tenant, first, "https://us.my.desk.test")
    await signed(world, tenant, second, "https://eu.my.desk.test")
    default = await world.registry.resolve(TOOL, tenant_id=tenant, team_id=TEAM, environment="production")
    named = await world.registry.resolve(
        TOOL, tenant_id=tenant, team_id=TEAM, environment="production", account="EU org"
    )
    assert default is not None and default.module is not None and named is not None and named.module is not None
    assert (default.module["connection_id"], default.module["endpoint"]) == (first, "https://us.my.desk.test/api/v1")
    assert (named.module["connection_id"], named.module["endpoint"]) == (second, "https://eu.my.desk.test/api/v1")


async def test_a_call_naming_an_account_the_team_does_not_hold_is_refused_not_defaulted(
    world: World, tenant: str
) -> None:
    await connected(world, tenant)
    await connected(world, tenant, OTHER)
    assert (await another(world, tenant, "Cards org", OTHER)).status_code == 201
    for name in ("No such org", "Cards org"):
        r = await world.registry.resolve(TOOL, tenant_id=tenant, team_id=TEAM, environment="production", account=name)
        assert r is not None and r.module is not None
        assert r.module.get("account_missing") and r.module["connection_id"] is None, (name, r.module)


async def test_a_persons_call_uses_the_account_they_pinned_else_their_newest_sign_in(world: World, tenant: str) -> None:
    first = await connected(world, tenant)
    second = (await another(world, tenant, "EU org")).json()["data"]["id"]
    await signed(world, tenant, first, "https://us.my.desk.test")
    await signed(world, tenant, second, "https://eu.my.desk.test")
    await signed(world, tenant, first, "https://us.my.desk.test", "usr_priya")
    await signed(world, tenant, second, "https://eu.my.desk.test", "usr_priya")

    async def used() -> str:
        r = await world.registry.resolve(
            TOOL, tenant_id=tenant, team_id=TEAM, environment="production", person="usr_priya"
        )
        assert r is not None and r.module is not None
        return str(r.module["connection_id"])

    assert await used() == second  # the newest of her sign-ins
    pinned = await world.client.put(f"/v1/connections/{first}/default", headers=admin(tenant))
    assert pinned.status_code == 200, pinned.text
    assert await used() == first
    page = (await world.client.get(f"/v1/apps/plugin:{ID}", headers=admin(tenant))).json()["data"]
    assert [(a["name"], a["mine"], a["pinned"]) for a in page["accounts"]] == [
        ("Desk", True, True),
        ("EU org", True, False),
    ]


async def test_with_several_accounts_off_a_second_account_cannot_be_made_or_named(world: World, tenant: str) -> None:
    world.host.accounts = False
    await connected(world, tenant)
    made = await another(world, tenant, "EU org")
    assert (made.status_code, made.json()["error"]["code"]) == (404, "feature_off"), made.text
    r = await world.registry.resolve(TOOL, tenant_id=tenant, team_id=TEAM, environment="production", account="Desk")
    assert r is not None and r.module is not None
    assert r.module.get("account_missing"), r.module


async def test_a_plugin_tools_page_names_the_teams_account_not_no_connection(
    world: World, tenant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plugin's module row is shared by every team, so it holds no connection; its page shows the calling team's
    default account, the one the gateway signs its calls in through, and another team's stays its own."""
    monkeypatch.setattr(ModuleService, "team_connections", world.host.team_connection)
    ours, theirs = await connected(world, tenant), await connected(world, tenant, OTHER)
    await world.host.ensure(tenant, datetime.now(UTC))
    module_id = module_id_of(desk.manifest)
    for team, conn in ((TEAM, ours), (OTHER, theirs)):
        got = await world.client.get(f"/v1/tool-modules/{module_id}", headers=admin(tenant, team))
        assert got.status_code == 200, got.text
        shown: dict[str, Any] = got.json()["data"]["connection"] or {}
        assert shown.get("id") == conn, shown


async def test_the_first_turn_on_names_the_teams_account(world: World, tenant: str) -> None:
    # The Connect window asks for the account's name; without it the account takes the app's title.
    on = await world.client.put(
        f"/v1/plugins/{ID}/team",
        json={"enabled": True, "clientId": "app", "accountName": "Billing desk"},
        headers=admin(tenant),
    )
    assert on.status_code == 200, on.text
    detail = await world.client.get(f"/v1/connections/{on.json()['data']['connectionId']}", headers=admin(tenant))
    assert detail.json()["data"]["accountName"] == "Billing desk", detail.text
