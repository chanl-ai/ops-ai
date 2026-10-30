"""A plugin's own app per environment (c-580), by failure mode: a second turn-on for the sandbox never reaches the
connection; a sandbox sign-in overwrites the production instance a live call goes to; a test call reaches production's
host; the team's client secret comes back in an answer; a plugin's card details are lost on the way to the console."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_plugin_sdk.loader import Loaded
from ops_tools.connections.service import ConnectionService
from ops_tools.plugins.host import PluginHost, module_id_of
from ops_tools.plugins.switches import InstallSwitches
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_app_keys import PluginAppKeys
from ops_tools.store.plugin_bindings import PluginBindings

from .plugin_desk import plugin as desk
from .test_plugin_credentials import (  # noqa: F401  # pyright: ignore[reportUnusedImport]
    TEAM,
    TEAM_SECRET,
    rig,  # pyright: ignore[reportUnusedImport]
    team_admin,
)
from .test_plugins import ID, Policy

Rig = tuple[httpx.AsyncClient, ConnectionService, PluginAppKeys]


async def test_a_second_turn_on_for_the_sandbox_sets_the_connections_test_environment(
    rig: Rig,  # noqa: F811
    tenant: str,
) -> None:
    client, connections, _ = rig
    admin = team_admin(tenant)
    on = await client.put(
        f"/v1/plugins/{ID}/team",
        json={"enabled": True, "clientId": "prod-app", "clientSecret": TEAM_SECRET},
        headers=admin,
    )
    assert on.status_code == 200, on.text
    conn_id = on.json()["data"]["connectionId"]
    sandbox = await client.put(
        f"/v1/plugins/{ID}/team",
        json={"enabled": True, "environment": "test", "clientId": "uat-app", "clientSecret": "uat-secret-41"},
        headers=admin,
    )
    assert sandbox.status_code == 200, sandbox.text
    assert sandbox.json()["data"]["connectionId"] == conn_id
    conn = await connections.store.get(tenant, conn_id)
    assert conn is not None
    envs: dict[str, Any] = conn["environments"]
    assert "test" in envs, "the sandbox's app never reached the connection"
    assert envs["test"]["settings"]["clientId"] == "uat-app"
    assert envs["production"]["settings"]["clientId"] == "prod-app", "the sandbox's app replaced production's"
    for answer in (on.text, sandbox.text):
        assert TEAM_SECRET not in answer and "uat-secret-41" not in answer


async def test_a_sandbox_sign_in_leaves_productions_instance_and_hosts_apart(
    engine: AsyncEngine,
    tenant: str,
    rig: Rig,  # noqa: F811
) -> None:
    client, _, _ = rig
    on = await client.put(
        f"/v1/plugins/{ID}/team", json={"enabled": True, "clientId": "prod-app"}, headers=team_admin(tenant)
    )
    conn_id = str(on.json()["data"]["connectionId"])
    host = PluginHost(
        ModuleStore(engine),
        PluginBindings(engine),
        InstallSwitches(Policy({ID: {"enabled": True, "client": {"id": "platform-client-id"}}})),
        [Loaded("desk", desk, None)],
    )
    await host.ensure(tenant, datetime.now(UTC))
    await host.on_token(tenant, conn_id, {"instance_url": "https://acme.my.desk.test"}, "production")
    await host.on_token(tenant, conn_id, {"instance_url": "https://acme--uat.my.desk.test"}, "test")
    module = await ModuleStore(engine).get(tenant, module_id_of(desk.manifest))
    assert module is not None
    live = await host.for_call(tenant, TEAM, module, "production")
    trial = await host.for_call(tenant, TEAM, module, "test")
    assert str(live["endpoint"]).startswith("https://acme.my.desk.test"), live["endpoint"]
    assert str(trial["endpoint"]).startswith("https://acme--uat.my.desk.test"), trial["endpoint"]
    assert "acme.my.desk.test" not in trial["egress_hosts"], "a test call may reach production's host"


async def test_a_plugin_answers_with_its_card_details(rig: Rig, tenant: str) -> None:  # noqa: F811
    client, _, _ = rig
    listed = await client.get("/v1/plugins", headers=team_admin(tenant))
    desk_view = next(p for p in listed.json()["data"]["plugins"] if p["id"] == ID)
    assert desk_view["display"] == {
        "logo": "https://desk.test/logo.svg",
        "category": "Service desk",
        "description": "Cases and their notes in Desk.",
        "docsUrl": "https://desk.test/docs/oauth-app",
    }, desk_view
