"""The one Turn on window's answer, through the real route, by failure mode: the sign-in place it asked once is kept
on the account only, so the auth config shows nothing and the next account must type it again, or is kept fixed, so a
second org can never sign in at its own address; whose account tools use is
left to the server's default (the team account only) instead of each person's own with the team account for runs
nobody started; and the app's tools are not all added, so a developer who connects it cannot write at once. Rig:
test_config_modes."""

from __future__ import annotations

from typing import Any

import httpx

from .test_config_modes import APP, OPS_AI_CONFIG, client  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_config_place import ACME
from .test_sign_in_place import admin


async def test_turning_on_offers_the_place_as_a_default_on_ops_ais_config_and_adds_every_tool(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    body: dict[str, Any] = {"enabled": True, "signIn": "person_or_team", "settings": {"login_url": ACME}}
    on = await client.put(f"/v1/apps/{APP}/team", json=body, headers=admin(tenant))
    assert on.status_code == 200, on.text
    card = on.json()["data"]
    account = str(card["connectionId"])
    page = (await client.get(f"/v1/apps/{APP}", headers=admin(tenant))).json()["data"]
    config = next(c for c in page["authConfigs"] if c["id"] == OPS_AI_CONFIG)
    field = next(f for f in config["fields"] if f["name"] == "login_url")
    assert (field["value"], field["mode"]) == (ACME, "default"), field
    detail = (await client.get(f"/v1/apps/{APP}/accounts/{account}", headers=admin(tenant))).json()["data"]
    assert (detail["signIn"], detail["teamBackup"]) == ("person_or_team", True), detail
    assert card["toolsAdded"] == len(page["tools"]) > 0 and all(t["added"] for t in page["tools"]), page["tools"]


async def test_turning_on_with_no_choice_runs_every_call_as_the_team_account(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    # A first turn-on that names no sign-in must not ask each person for their own account before their first call;
    # per-person sign-in stays a choice an admin makes on the app's settings.
    on = await client.put(
        f"/v1/apps/{APP}/team", json={"enabled": True, "settings": {"login_url": ACME}}, headers=admin(tenant)
    )
    assert on.status_code == 200, on.text
    account = str(on.json()["data"]["connectionId"])
    detail = (await client.get(f"/v1/apps/{APP}/accounts/{account}", headers=admin(tenant))).json()["data"]
    assert detail["signIn"] == "team", detail
