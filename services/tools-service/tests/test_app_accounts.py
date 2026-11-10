"""A team keeps several named accounts of one app, by failure mode: a second account replaces the first; a
sign-in on the second account settles the first's instance; a call naming an account runs with another, or with
another team's; and a person's call ignores the account they pinned."""

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
from ops_tools.modules.seed import load
from ops_tools.modules.service import ModuleService
from ops_tools.modules.tool_users import StaticToolUsers
from ops_tools.plugins.host import PluginHost, module_id_of
from ops_tools.registry import ToolRegistry
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings

from .conftest import build_app, response_checker, team_credential
from .plugin_desk import plugin as desk
from .test_plugin_credentials import INSTALL
from .test_plugins import ID
from .test_review_decisions import introspect, jwks, person

TEAM = "team_platform"
OTHER = "team_cards"
TOOL = "desk_get_case"
APP = f"plugin:{ID}"


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
    services = ServiceAuth(
        audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes
    )
    # A service reaches the public routes too, as agents-service does asking for a person (acting for them).
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0, services=services), services
    )
    store = ConnectionStore(engine, INSTALL)
    host = PluginHost(
        ModuleStore(engine),
        PluginBindings(engine),
        {},
        [Loaded("desk", desk, None)],
        store,
    )
    users = StaticToolUsers()
    app = build_app(engine, seed, tenant, auth=auth, install_clients=INSTALL, plugins=host, users=users)
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        yield World(c, host, ToolRegistry(local_catalog, ModuleStore(engine), host), store, users)


def admin(tenant: str, team: str = TEAM) -> dict[str, str]:
    return person(tenant, "Priya Shah", {team: "admin"})


async def connected(w: World, tenant: str, team: str = TEAM) -> str:
    """The team's first Desk account, on with the team's own app; its connection id."""
    credential = await team_credential(w.client, admin(tenant, team), APP)
    on = await w.client.put(
        f"/v1/apps/plugin:{ID}/team", json={"enabled": True, "credentialId": credential}, headers=admin(tenant, team)
    )
    assert on.status_code == 200, on.text
    return str(on.json()["data"]["connectionId"])


async def another(w: World, tenant: str, name: str, team: str = TEAM) -> httpx.Response:
    body = {"name": name, "credentialId": await team_credential(w.client, admin(tenant, team), APP, "eu-app")}
    return await w.client.post(f"/v1/apps/plugin:{ID}/accounts", json=body, headers=admin(tenant, team))


async def signed(w: World, tenant: str, connection_id: str, instance: str, person_id: str = "") -> None:
    """A finished sign-in on the account: the instance its token named, and its token row (the team's or a person's)."""
    await w.host.on_token(tenant, connection_id, {"instance_url": instance})
    await w.store.replace_token(
        tenant,
        connection_id,
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
    assert second["id"].startswith("ca_") and second["accountName"] == "EU org" and second["appId"] == APP
    page = (await world.client.get(f"/v1/apps/plugin:{ID}", headers=admin(tenant))).json()["data"]
    listed = sorted((a["id"], a["name"], a["default"]) for a in page["accounts"] if a["kind"] == "team")
    assert listed == sorted([(first, "Desk", True), (second["id"], "EU org", False)]), listed
    again = await another(world, tenant, "eu ORG")
    assert again.status_code == 409, again.text


async def test_a_sign_in_on_the_second_account_settles_its_own_instance_and_a_call_naming_it_uses_it(
    world: World, tenant: str
) -> None:
    first = await connected(world, tenant)
    second = (await another(world, tenant, "EU org")).json()["data"]["id"]
    await signed(world, tenant, first, "https://us.my.desk.test")
    await signed(world, tenant, second, "https://eu.my.desk.test")
    default = await world.registry.resolve(TOOL, tenant_id=tenant, team_id=TEAM, run="live")
    named = await world.registry.resolve(TOOL, tenant_id=tenant, team_id=TEAM, run="live", account="EU org")
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
        r = await world.registry.resolve(TOOL, tenant_id=tenant, team_id=TEAM, run="live", account=name)
        assert r is not None and r.module is not None
        assert r.module.get("account_missing") and r.module["connection_id"] is None, (name, r.module)


async def test_a_persons_call_asks_which_account_until_they_save_a_default(world: World, tenant: str) -> None:
    first = await connected(world, tenant)
    second = (await another(world, tenant, "EU org")).json()["data"]["id"]
    await signed(world, tenant, first, "https://us.my.desk.test")
    await signed(world, tenant, second, "https://eu.my.desk.test")
    await signed(world, tenant, first, "https://us.my.desk.test", "usr_priya")
    await signed(world, tenant, second, "https://eu.my.desk.test", "usr_priya")

    async def used() -> dict[str, Any]:
        r = await world.registry.resolve(TOOL, tenant_id=tenant, team_id=TEAM, run="live", person="usr_priya")
        assert r is not None and r.module is not None
        return dict(r.module)

    async def shown() -> dict[str, bool | None]:
        """Her accounts on the app page: which one it names as her default."""
        page = (await world.client.get(f"/v1/apps/plugin:{ID}", headers=admin(tenant))).json()["data"]
        return {a["name"]: a["myDefault"] for a in page["accounts"] if a["kind"] == "team" if a["mine"]}

    # Two of her sign-ins fit and she saved neither: the call asks which, and the page names no default.
    asked = await used()
    assert asked.get("account_choice") is not None and asked["connection_id"] is None, asked
    assert await shown() == {"Desk": False, "EU org": False}
    pinned = await world.client.put(f"/v1/apps/{APP}/accounts/{first}/default", headers=admin(tenant))
    assert pinned.status_code == 200, pinned.text
    assert (await used())["connection_id"] == first
    assert await shown() == {"Desk": True, "EU org": False}


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
        f"/v1/apps/plugin:{ID}/team",
        json={"enabled": True, "accountName": "Billing desk"},
        headers=admin(tenant),
    )
    assert on.status_code == 200, on.text
    detail = await world.client.get(
        f"/v1/apps/{APP}/accounts/{on.json()['data']['connectionId']}",
        headers=admin(tenant),
    )
    assert detail.json()["data"]["accountName"] == "Billing desk", detail.text


async def test_an_account_a_step_or_agent_names_is_not_deleted_until_nothing_names_it(
    world: World, tenant: str
) -> None:
    await connected(world, tenant)
    made = await another(world, tenant, "EU org")
    eu = str(made.json()["data"]["id"])
    world.users.account_uses[(APP, "eu org")] = {"drafts": 1, "published": 2, "workflows": ["wf_a"], "agents": ["ag_b"]}
    refused = await world.client.delete(f"/v1/apps/plugin:{ID}/accounts/{eu}", headers=admin(tenant))
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "account_in_use", refused.text
    error = refused.json()["error"]
    assert (error["details"]["published"], error["details"]["drafts"]) == (2, 1), error
    assert "2 published" in error["message"] and "1 draft" in error["message"], error
    world.users.account_uses.clear()
    gone = await world.client.delete(f"/v1/apps/plugin:{ID}/accounts/{eu}", headers=admin(tenant))
    assert gone.status_code == 204, gone.text


async def test_each_account_counts_the_people_signed_in_to_it_and_says_who_signs_in(world: World, tenant: str) -> None:
    """The "Each person signs in" card shows how many people signed in to that account, so a count read off the
    team's default, or off every account of the app, says the wrong number on the second account."""
    first = await connected(world, tenant)
    second = (await another(world, tenant, "EU org")).json()["data"]
    each = await world.client.patch(
        f"/v1/apps/{APP}/accounts/{second['id']}",
        json={"revision": second["revision"], "signIn": "person_or_team"},
        headers=admin(tenant),
    )
    assert each.status_code == 200, each.text
    await signed(world, tenant, first, "https://us.my.desk.test", "usr_priya")
    await signed(world, tenant, second["id"], "https://eu.my.desk.test", "usr_priya")
    await signed(world, tenant, second["id"], "https://eu.my.desk.test", "usr_maya")
    page = (await world.client.get(f"/v1/apps/{APP}", headers=admin(tenant))).json()["data"]
    rows = {a["name"]: (a["signIn"], a["peopleSignedIn"]) for a in page["accounts"] if a["kind"] == "team"}
    assert rows == {"Desk": ("team", 1), "EU org": ("person_or_team", 2)}, rows
