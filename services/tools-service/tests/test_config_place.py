"""Where an account signs in when its plugin asks for the address on the auth config (`asked: config`), through the
real routes, by failure mode: the account keeps its own address, so two accounts of one config sign in at different
orgs and editing the config changes nothing; the config takes a value outside the plugin's choices; and the config's
answer leaves out the field's choices and host check, so its windows cannot ask the question. Rig: test_sign_in_place's
routes with a plugin whose login_url is `asked: config`."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_plugin_sdk.loader import Loaded
from ops_service_kit.settings import PluginClient
from ops_tools.modules.seed import load
from ops_tools.plugins.host import PluginHost
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings

from .conftest import build_app, response_checker, team_credential
from .plugin_config_place import plugin as config_place
from .test_sign_in_place import admin, person_auth

ID = "test.configplace"
APP = f"plugin:{ID}"
INSTALL = {ID: PluginClient(id="ops-ai-config", secret=SecretStr("ops-ai-config-secret"))}
ACME = "https://acme.my.signin.test/oauth2"


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


async def _authorize_url(client: httpx.AsyncClient, tenant: str, account: str) -> str:
    detail = (await client.get(f"/v1/apps/{APP}/accounts/{account}", headers=admin(tenant))).json()["data"]
    return str(detail["settings"].get("authorizeUrl"))


async def test_accounts_sign_in_at_their_configs_address_and_follow_an_edit(
    client: httpx.AsyncClient, tenant: str
) -> None:
    config = await team_credential(
        client, admin(tenant), APP, "config-own", "s3cret-value", settings={"login_url": ACME}
    )
    on = await client.put(f"/v1/apps/{APP}/team", json={"enabled": True, "credentialId": config}, headers=admin(tenant))
    assert on.status_code == 200, on.text
    first = str(on.json()["data"]["connectionId"])
    made = await client.post(
        f"/v1/apps/{APP}/accounts", json={"name": "Second org", "credentialId": config}, headers=admin(tenant)
    )
    assert made.status_code == 201, made.text
    second = str(made.json()["data"]["id"])
    assert await _authorize_url(client, tenant, first) == f"{ACME}/common/authorize"
    assert await _authorize_url(client, tenant, second) == f"{ACME}/common/authorize"

    moved = "https://test.signin.test/oauth2"
    edited = await client.patch(
        f"/v1/app-credentials/{config}", json={"settings": {"login_url": moved}}, headers=admin(tenant)
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["data"]["signInAgain"] == 2, edited.text
    for account in (first, second):
        assert await _authorize_url(client, tenant, account) == f"{moved}/common/authorize"


async def test_a_config_refuses_an_address_outside_the_plugins_choices_in_a_plain_sentence(
    client: httpx.AsyncClient, tenant: str
) -> None:
    body = {
        "app": APP,
        "clientId": "c",
        "clientSecret": "s3cret-value",
        "settings": {"login_url": "https://evil.example"},
    }
    refused = await client.post("/v1/app-credentials", json=body, headers=admin(tenant))
    assert refused.status_code == 400, refused.text
    message = refused.json()["error"]["message"]
    assert "your company's address ending in .my.signin.test" in message and "login_url" not in message, message


async def test_the_configs_answer_carries_the_fields_choices_and_host_check(
    client: httpx.AsyncClient, tenant: str
) -> None:
    config = await team_credential(
        client, admin(tenant), APP, "config-own", "s3cret-value", settings={"login_url": ACME}
    )
    page = (await client.get(f"/v1/app-credentials/{config}", headers=admin(tenant))).json()["data"]
    field = next(f for f in page["fields"] if f["name"] == "login_url")
    assert [c["label"] for c in field["choices"]] == ["login.signin.test", "test.signin.test"], field
    assert field["other"]["hosts"] == [".my.signin.test"] and page["settings"]["login_url"] == ACME, field
    card = (await client.get(f"/v1/apps/{APP}", headers=admin(tenant))).json()["data"]["card"]
    asked = {s["name"]: s.get("asked") for s in card["plugin"]["settings"]}
    assert asked["login_url"] == "config", asked


async def test_a_config_that_leaves_the_address_unset_lets_each_account_give_its_own(
    client: httpx.AsyncClient, tenant: str
) -> None:
    # Ops AI's app is the install's and sets no address, so each account says where it signs in, as a team's own
    # config with the field left empty does.
    sandbox = "https://test.signin.test/oauth2"
    on = await client.put(
        f"/v1/apps/{APP}/team", json={"enabled": True, "settings": {"login_url": ACME}}, headers=admin(tenant)
    )
    assert on.status_code == 200, on.text
    first = str(on.json()["data"]["connectionId"])
    config = await team_credential(client, admin(tenant), APP, "config-empty", "s3cret-value")
    made = await client.post(
        f"/v1/apps/{APP}/accounts",
        json={"name": "Sandbox", "credentialId": config, "settings": {"login_url": sandbox}},
        headers=admin(tenant),
    )
    assert made.status_code == 201, made.text
    assert await _authorize_url(client, tenant, first) == f"{ACME}/common/authorize"
    assert await _authorize_url(client, tenant, str(made.json()["data"]["id"])) == f"{sandbox}/common/authorize"
