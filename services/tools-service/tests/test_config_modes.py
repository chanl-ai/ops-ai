"""An auth config's sign-in value held as a default or fixed, through the real routes, by failure mode: a fixed value
is every account's and is not asked; a default is where an account starts, an account may sign in elsewhere, and
changing it signs nobody in again; a mode with no value is refused; and the team's values on Ops AI's own app are
kept per team, change only where it signs in, and are what an account on it signs in with. Rig: test_config_place."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_plugin_sdk.loader import Loaded
from ops_tools.modules.seed import load
from ops_tools.plugins.host import PluginHost
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings

from .conftest import build_app, response_checker, team_credential
from .plugin_config_place import plugin as config_place
from .test_config_place import ACME, APP, INSTALL, _authorize_url  # pyright: ignore[reportPrivateUsage]
from .test_sign_in_place import admin, person_auth

SANDBOX = "https://test.signin.test/oauth2"
OPS_AI_CONFIG = f"ops-ai:{APP}"


@pytest.fixture
async def client(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[httpx.AsyncClient]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    store = ConnectionStore(engine, INSTALL)
    host = PluginHost(ModuleStore(engine), PluginBindings(engine), {}, [Loaded("config", config_place, None)], store)
    app = build_app(engine, seed, tenant, auth=person_auth(), install_clients=INSTALL, plugins=host)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://tools",
        event_hooks={"response": [response_checker(app)]},
    ) as c:
        yield c


async def _config(c: httpx.AsyncClient, tenant: str, config_id: str) -> dict[str, Any]:
    configs = (await c.get(f"/v1/apps/{APP}", headers=admin(tenant))).json()["data"]["authConfigs"]
    return next(x for x in configs if x["id"] == config_id)


def _field(config: dict[str, Any]) -> dict[str, Any]:
    return next(f for f in config["fields"] if f["name"] == "login_url")


async def test_a_value_given_no_mode_is_fixed_and_every_account_signs_in_there(
    client: httpx.AsyncClient, tenant: str
) -> None:
    config = await team_credential(client, admin(tenant), APP, "c", "s3cret-value", settings={"login_url": ACME})
    field = _field(await _config(client, tenant, config))
    assert (field["value"], field["mode"], field["shown"]) == (ACME, "fixed", "acme.my.signin.test"), field
    made = await client.post(
        f"/v1/apps/{APP}/accounts",
        json={"name": "Elsewhere", "credentialId": config, "settings": {"login_url": SANDBOX}},
        headers=admin(tenant),
    )
    assert made.status_code == 201, made.text
    # The account asked for another place; a fixed value wins.
    assert await _authorize_url(client, tenant, str(made.json()["data"]["id"])) == f"{ACME}/common/authorize"


async def test_a_default_is_where_an_account_starts_and_one_may_sign_in_elsewhere(
    client: httpx.AsyncClient, tenant: str
) -> None:
    config = await team_credential(
        client, admin(tenant), APP, "c", "s3cret-value", settings={"login_url": ACME}, modes={"login_url": "default"}
    )
    assert _field(await _config(client, tenant, config))["mode"] == "default"
    started = await client.post(
        f"/v1/apps/{APP}/accounts", json={"name": "Default", "credentialId": config}, headers=admin(tenant)
    )
    moved = await client.post(
        f"/v1/apps/{APP}/accounts",
        json={"name": "Sandbox", "credentialId": config, "settings": {"login_url": SANDBOX}},
        headers=admin(tenant),
    )
    assert started.status_code == 201 and moved.status_code == 201, (started.text, moved.text)
    first, second = str(started.json()["data"]["id"]), str(moved.json()["data"]["id"])
    assert await _authorize_url(client, tenant, first) == f"{ACME}/common/authorize"
    assert await _authorize_url(client, tenant, second) == f"{SANDBOX}/common/authorize"

    # A new default is where the next account starts: the accounts keep their place and need no new sign-in.
    elsewhere = "https://other.my.signin.test/oauth2"
    edited = await client.patch(
        f"/v1/app-credentials/{config}", json={"settings": {"login_url": elsewhere}}, headers=admin(tenant)
    )
    assert edited.status_code == 200 and edited.json()["data"]["signInAgain"] == 0, edited.text
    assert await _authorize_url(client, tenant, first) == f"{ACME}/common/authorize"
    assert await _authorize_url(client, tenant, second) == f"{SANDBOX}/common/authorize"

    # Made fixed, it is every account's, and both sign in again.
    fixed = await client.patch(
        f"/v1/app-credentials/{config}", json={"modes": {"login_url": "fixed"}}, headers=admin(tenant)
    )
    assert fixed.status_code == 200 and fixed.json()["data"]["signInAgain"] == 2, fixed.text
    for account in (first, second):
        assert await _authorize_url(client, tenant, account) == f"{elsewhere}/common/authorize"


async def test_a_mode_for_a_value_the_config_does_not_hold_is_refused(client: httpx.AsyncClient, tenant: str) -> None:
    body = {"app": APP, "clientId": "c", "clientSecret": "s3cret-value", "modes": {"login_url": "default"}}
    refused = await client.post("/v1/app-credentials", json=body, headers=admin(tenant))
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "mode_without_value", refused.text


async def test_the_teams_value_on_ops_ais_app_is_where_its_accounts_sign_in(
    client: httpx.AsyncClient, tenant: str
) -> None:
    before = await _config(client, tenant, OPS_AI_CONFIG)
    assert before["canEdit"] and before["clientId"] == "ops-ai-config" and _field(before)["value"] is None, before
    renamed = await client.patch(f"/v1/app-credentials/{OPS_AI_CONFIG}", json={"name": "Mine"}, headers=admin(tenant))
    assert renamed.status_code == 400 and renamed.json()["error"]["code"] == "ops_ai_app", renamed.text

    saved = await client.patch(
        f"/v1/app-credentials/{OPS_AI_CONFIG}", json={"settings": {"login_url": ACME}}, headers=admin(tenant)
    )
    assert saved.status_code == 200, saved.text
    after = await _config(client, tenant, OPS_AI_CONFIG)
    assert (_field(after)["value"], _field(after)["mode"], after["signInPlace"]) == (ACME, "fixed", ACME), after
    on = await client.put(f"/v1/apps/{APP}/team", json={"enabled": True}, headers=admin(tenant))
    assert on.status_code == 200, on.text
    assert await _authorize_url(client, tenant, str(on.json()["data"]["connectionId"])) == f"{ACME}/common/authorize"
