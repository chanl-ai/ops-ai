"""An OAuth app with nothing to sign in through, by failure mode: the card reads as an app the team can turn on (Turn on
then cannot finish, and nothing says why); an account whose auth config holds no client secret reads as only needing
a sign-in that cannot work. Rig: test_plugin_removed, an install with no app of Ops AI's own for Desk."""

from __future__ import annotations

from typing import Any

from .conftest import team_credential
from .test_plugin_credentials import team_admin
from .test_plugin_removed import Rig, rig  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_plugins import ID

APP = f"plugin:{ID}"


async def card(client: Any, tenant: str) -> dict[str, Any]:
    r = await client.get(f"/v1/apps/{APP}", headers=team_admin(tenant))
    assert r.status_code == 200, r.text
    return r.json()["data"]["card"]


async def test_an_app_with_no_auth_config_says_to_add_one_then_is_off(rig: Rig, tenant: str) -> None:  # noqa: F811
    client, _ = rig
    c = await card(client, tenant)
    assert (c["appState"], c["appStateReason"]) == ("needs_auth_config", "Add an auth config for Desk first."), c
    assert c["appGroup"] == "needs_admin", c
    await team_credential(client, team_admin(tenant), APP)
    assert (await card(client, tenant))["appState"] == "off"


async def test_an_account_on_an_auth_config_with_no_secret_needs_one(rig: Rig, tenant: str) -> None:  # noqa: F811
    client, _ = rig
    made = await client.post("/v1/app-credentials", json={"app": APP, "clientId": "app"}, headers=team_admin(tenant))
    assert made.status_code == 201, made.text
    cred = str(made.json()["data"]["id"])
    on = await client.put(
        f"/v1/apps/{APP}/team", json={"enabled": True, "credentialId": cred}, headers=team_admin(tenant)
    )
    assert on.status_code == 200, on.text
    c = await card(client, tenant)
    # On for the team with a broken config is its own state, and the team's: an admin fixes the config.
    assert (c["appState"], c["appGroup"]) == ("auth_config_broken", "needs_admin"), c
    assert "no client secret" in str(c["appStateReason"]), c
    put = await client.put(
        f"/v1/app-credentials/{cred}/secret", json={"clientSecret": "s3cret"}, headers=team_admin(tenant)
    )
    assert put.status_code == 200, put.text
    assert (await card(client, tenant))["appState"] == "needs_sign_in"


async def _on_without_a_working_config(client: Any, tenant: str) -> str:
    made = await client.post("/v1/app-credentials", json={"app": APP, "clientId": "app"}, headers=team_admin(tenant))
    assert made.status_code == 201, made.text
    cred = str(made.json()["data"]["id"])
    on = await client.put(
        f"/v1/apps/{APP}/team", json={"enabled": True, "credentialId": cred}, headers=team_admin(tenant)
    )
    assert on.status_code == 200, on.text
    return cred


async def test_another_working_config_turns_a_broken_one_into_a_sign_in_through_it(rig: Rig, tenant: str) -> None:  # noqa: F811
    # Adding a config clears the broken state: the account signs in again through the new one.
    client, _ = rig
    await _on_without_a_working_config(client, tenant)
    assert (await card(client, tenant))["appState"] == "auth_config_broken"
    await team_credential(client, team_admin(tenant), APP, "second")
    c = await card(client, tenant)
    assert (c["appState"], c["appGroup"]) == ("needs_sign_in", "needs_admin"), c
    assert "Sign in again through another" in str(c["appStateReason"]), c


async def test_a_deleted_config_leaves_the_app_broken_and_turn_off_still_works(rig: Rig, tenant: str) -> None:  # noqa: F811
    client, host = rig
    cred = await _on_without_a_working_config(client, tenant)
    # The config's row is gone, as a delete outside the move path would leave it.
    assert host.connections is not None
    await host.connections.delete_credential(tenant, cred)
    assert (await card(client, tenant))["appState"] == "auth_config_broken"
    # The app is on for the team, so Settings' Turn off works and the team's state reads off with nothing to sign in.
    off = await client.put(f"/v1/apps/{APP}/team", json={"enabled": False}, headers=team_admin(tenant))
    assert off.status_code == 200, off.text
    assert off.json()["data"]["appState"] == "needs_auth_config", off.json()["data"]
