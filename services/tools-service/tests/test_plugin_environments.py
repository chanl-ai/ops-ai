"""A plugin's sandbox account beside its live one (c-580, c-608), by failure mode: the sandbox's own app never reaches
its account, or replaces the live account's; a sandbox sign-in overwrites the instance a live call goes to; a test call
reaches the live account's host; the team's client secret comes back in an answer; a plugin's card details are lost on
the way to the console; a removed account's instance reaches the account made after it."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_plugin_sdk.loader import Loaded
from ops_tools.plugins.host import PluginHost, module_id_of
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings

from .plugin_desk import plugin as desk
from .test_plugin_credentials import (  # noqa: F401  # pyright: ignore[reportUnusedImport]
    APP,
    TEAM,
    TEAM_SECRET,
    Rig,
    rig,  # pyright: ignore[reportUnusedImport]
    team_admin,
)

LIVE = "https://acme.my.desk.test"
UAT = "https://acme--uat.my.desk.test"


def desk_host(engine: AsyncEngine) -> PluginHost:
    """The desk plugin as the service serves it, reading each account's own settings from the accounts."""
    return PluginHost(
        ModuleStore(engine), PluginBindings(engine), {}, [Loaded("desk", desk, None)], ConnectionStore(engine)
    )


async def _sandbox(client: httpx.AsyncClient, tenant: str, **body: str) -> httpx.Response:
    return await client.post(
        f"/v1/apps/{APP}/accounts", json={"name": "UAT", "sandbox": True, **body}, headers=team_admin(tenant)
    )


async def test_a_sandbox_account_keeps_its_own_app_and_the_live_account_keeps_its(
    rig: Rig,  # noqa: F811
    tenant: str,
) -> None:
    client, connections, _ = rig
    admin = team_admin(tenant)
    on = await client.put(
        f"/v1/apps/{APP}/team",
        json={"enabled": True, "clientId": "prod-app", "clientSecret": TEAM_SECRET},
        headers=admin,
    )
    assert on.status_code == 200, on.text
    live_id = on.json()["data"]["connectionId"]
    made = await _sandbox(client, tenant, clientId="uat-app", clientSecret="uat-secret-41")
    assert made.status_code == 201, made.text
    sandbox_id = made.json()["data"]["id"]
    assert sandbox_id != live_id
    live = await connections.store.get(tenant, live_id)
    sandbox = await connections.store.get(tenant, sandbox_id)
    assert live is not None and sandbox is not None
    assert sandbox["sandbox"] and sandbox["settings"]["clientId"] == "uat-app", "the sandbox's app never reached it"
    assert not live["sandbox"] and live["settings"]["clientId"] == "prod-app", "the sandbox's app replaced the live one"
    card = (await client.get(f"/v1/apps/{APP}", headers=admin)).json()["data"]["card"]
    assert (card["connectionId"], card["sandboxId"]) == (live_id, sandbox_id), card
    for answer in (on.text, made.text):
        assert TEAM_SECRET not in answer and "uat-secret-41" not in answer


async def test_a_sandbox_sign_in_leaves_the_live_accounts_instance_and_hosts_apart(
    engine: AsyncEngine,
    tenant: str,
    rig: Rig,  # noqa: F811
) -> None:
    client, connections, _ = rig
    on = await client.put(
        f"/v1/apps/{APP}/team", json={"enabled": True, "clientId": "prod-app"}, headers=team_admin(tenant)
    )
    live_id = str(on.json()["data"]["connectionId"])
    made = await _sandbox(client, tenant, clientId="uat-app")
    assert made.status_code == 201, made.text
    sandbox_id = str(made.json()["data"]["id"])
    host = desk_host(engine)
    await host.ensure(tenant, datetime.now(UTC))
    await host.on_token(tenant, live_id, {"instance_url": LIVE})
    await host.on_token(tenant, sandbox_id, {"instance_url": UAT})
    live = await connections.store.get(tenant, live_id)
    assert live is not None and live["plugin_settings"]["instance_url"] == LIVE, "the sandbox sign-in overwrote it"
    module = await ModuleStore(engine).get(tenant, module_id_of(desk.manifest))
    assert module is not None
    production = await host.for_call(tenant, TEAM, module, "production")
    trial = await host.for_call(tenant, TEAM, module, "test")
    assert production["connection_id"] == live_id and not production["sandbox"], production
    assert str(production["endpoint"]).startswith(LIVE), production["endpoint"]
    assert trial["connection_id"] == sandbox_id and trial["sandbox"], trial
    assert str(trial["endpoint"]).startswith(UAT), trial["endpoint"]
    assert "acme.my.desk.test" not in trial["egress_hosts"], "a test call may reach the live account's host"


async def test_a_plugin_answers_with_its_card_details(rig: Rig, tenant: str) -> None:  # noqa: F811
    client, _, _ = rig
    listed = await client.get("/v1/apps", headers=team_admin(tenant))
    card = next(c for c in listed.json()["data"] if c["id"] == APP)
    shown = {k: card[k] for k in ("logo", "category", "description", "docsUrl")}
    assert shown == {
        "logo": "https://desk.test/logo.svg",
        "category": "Service desk",
        "description": "Cases and their notes in Desk.",
        "docsUrl": "https://desk.test/docs/oauth-app",
    }, card


async def test_a_new_account_never_calls_the_instance_a_removed_one_signed_in_to(
    engine: AsyncEngine,
    tenant: str,
    rig: Rig,  # noqa: F811
) -> None:
    """An account's own settings are kept once, on the account (c-580). A copy on the team's binding would outlive the
    account it came from: after Cancel removed one, the next account would call the old instance before anyone signed
    in to it."""
    client, _, _ = rig
    admin = team_admin(tenant)
    host = desk_host(engine)
    await host.ensure(tenant, datetime.now(UTC))
    first = await client.put(f"/v1/apps/{APP}/team", json={"enabled": True, "clientId": "prod-app"}, headers=admin)
    old = str(first.json()["data"]["connectionId"])
    await host.on_token(tenant, old, {"instance_url": LIVE})
    assert (await client.delete(f"/v1/apps/{APP}/accounts/{old}", headers=admin)).status_code in (200, 204)
    again = await client.put(f"/v1/apps/{APP}/team", json={"enabled": True, "clientId": "prod-app"}, headers=admin)
    assert again.status_code == 200 and again.json()["data"]["connectionId"] != old, again.text
    module = await ModuleStore(engine).get(tenant, module_id_of(desk.manifest))
    assert module is not None
    seen = await host.for_call(tenant, TEAM, module, "production")
    assert "acme.my.desk.test" not in str(seen.get("endpoint")), "the new account calls the removed one's instance"
    # Not signed in yet reads as a missing instance, not as the plugin being off.
    assert seen.get("instance_missing") and not seen.get("plugin_off"), seen
    # Signed in again, the new account's own instance is the one a call uses.
    await host.on_token(tenant, str(again.json()["data"]["connectionId"]), {"instance_url": "https://new.my.desk.test"})
    seen = await host.for_call(tenant, TEAM, module, "production")
    assert str(seen["endpoint"]).startswith("https://new.my.desk.test"), seen["endpoint"]


async def test_a_plugin_tools_address_is_none_until_the_sign_in_names_its_instance(
    engine: AsyncEngine,
    tenant: str,
    rig: Rig,  # noqa: F811
) -> None:
    """Turned on, the account holds the sign-in host, where its credentials go. Shown as the tools' address, a tool page
    read login.desk.test as where the tools run."""
    client, connections, _ = rig
    admin = team_admin(tenant)
    host = desk_host(engine)
    await host.ensure(tenant, datetime.now(UTC))
    on = await client.put(f"/v1/apps/{APP}/team", json={"enabled": True, "clientId": "prod-app"}, headers=admin)
    live_id = str(on.json()["data"]["connectionId"])
    path = f"/v1/tool-modules/{module_id_of(desk.manifest)}"
    before = (await client.get(path, headers=admin)).json()["data"]
    assert before["connection"] is not None and before["connection"]["id"] == live_id, before["connection"]
    assert before["endpoint"] is None and before["connection"]["baseUrl"] is None, (
        before["endpoint"],
        before["connection"],
    )
    # The sign-in saves the instance on the account and its origin as the account's address (connections.service).
    await host.on_token(tenant, live_id, {"instance_url": LIVE})
    await connections.store.set_base(tenant, live_id, LIVE, actor="test", at=datetime.now(UTC))
    after = (await client.get(path, headers=admin)).json()["data"]
    assert after["endpoint"] == LIVE and after["connection"]["baseUrl"] == LIVE, (
        after["endpoint"],
        after["connection"],
    )
