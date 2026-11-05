"""Where a plugin's account signs in, through the real routes, by failure mode: a value outside the plugin's choices is
saved, so the sign-in sends a person (and later the token) to a host outside the system; a typed host that only
looks like the plugin's suffix gets through; a second account skips the check the first one had; and the app's answer
leaves the choices out, so the Connect window cannot ask the question without knowing the plugin."""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_plugin_sdk.loader import Loaded
from ops_service_kit.settings import PluginClient, Settings
from ops_tools.modules.seed import load
from ops_tools.plugins.host import PluginHost
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings

from .conftest import build_app, response_checker
from .plugin_signin import plugin as signin
from .test_review_decisions import introspect, jwks, person

TEAM = "team_platform"
ID = "test.signin"
APP = f"plugin:{ID}"
INSTALL = {ID: PluginClient(id="ops-ai-signin", secret=SecretStr("ops-ai-signin-secret"))}


def signin_host(engine: AsyncEngine, store: ConnectionStore) -> PluginHost:
    return PluginHost(ModuleStore(engine), PluginBindings(engine), {}, [Loaded("signin", signin, None)], store)


def person_auth() -> Auth:
    settings = Settings()
    return Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes),
    )


@asynccontextmanager
async def signin_client(
    engine: AsyncEngine,
    seed: dict[str, Any],
    tenant: str,
    catalog_tools: list[dict[str, Any]],
    upstream: httpx.AsyncClient | None = None,
) -> AsyncGenerator[httpx.AsyncClient]:
    """The real routes with the sign-in test plugin installed and Ops AI's app set up for it; `upstream` is the
    system's sign-in, for a test that exchanges a code."""
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    store = ConnectionStore(engine, INSTALL)
    app = build_app(
        engine,
        seed,
        tenant,
        auth=person_auth(),
        install_clients=INSTALL,
        plugins=signin_host(engine, store),
        upstream=upstream,
    )
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        yield c


@pytest.fixture
async def client(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[httpx.AsyncClient]:
    async with signin_client(engine, seed, tenant, catalog_tools) as c:
        yield c


def admin(tenant: str) -> dict[str, str]:
    return person(tenant, "Priya Shah", {TEAM: "admin"})


async def _turn_on(client: httpx.AsyncClient, tenant: str, login_url: str) -> httpx.Response:
    body = {"enabled": True, "settings": {"login_url": login_url}}
    return await client.put(f"/v1/apps/{APP}/team", json=body, headers=admin(tenant))


async def test_a_sign_in_place_outside_the_choices_is_refused_before_any_account(
    client: httpx.AsyncClient, tenant: str
) -> None:
    refused = await _turn_on(client, tenant, "https://login.evil.example/oauth2")
    assert refused.status_code == 400, refused.text
    error = refused.json()["error"]
    assert error["code"] == "setting_not_offered" and error["details"] == {"field": "login_url"}, error
    assert "login.signin.test, test.signin.test or your company's address ending in .my.signin.test" in error["message"]
    card = (await client.get(f"/v1/apps/{APP}", headers=admin(tenant))).json()["data"]["card"]
    assert card["connectionId"] is None and card["plugin"]["teamOn"] is False, card


@pytest.mark.parametrize(
    "typed",
    [
        "https://acme.my.signin.test.evil.example/oauth2",
        "https://evil.example/acme.my.signin.test/oauth2",
        "https://acme.my.signin.test:8443/oauth2",
        "https://user@acme.my.signin.test/oauth2",
        "https://.my.signin.test/oauth2",
        "https://acme.my.signin.test/oauth2/../steal",
    ],
)
async def test_a_typed_host_that_only_looks_like_the_systems_is_refused(
    client: httpx.AsyncClient, tenant: str, typed: str
) -> None:
    refused = await _turn_on(client, tenant, typed)
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "setting_not_offered", refused.text


async def test_a_choice_and_a_typed_company_host_are_both_taken(client: httpx.AsyncClient, tenant: str) -> None:
    on = await _turn_on(client, tenant, "https://acme.my.signin.test/oauth2")
    assert on.status_code == 200, on.text
    account = on.json()["data"]["connectionId"]
    detail = (await client.get(f"/v1/apps/{APP}/accounts/{account}", headers=admin(tenant))).json()["data"]
    assert detail["settings"]["authorizeUrl"] == "https://acme.my.signin.test/oauth2/common/authorize", detail


async def test_another_account_is_checked_as_the_first_was(client: httpx.AsyncClient, tenant: str) -> None:
    assert (await _turn_on(client, tenant, "https://login.signin.test/oauth2")).status_code == 200
    body = {"name": "Testing org", "sandbox": True, "settings": {"login_url": "https://test.evil.example/oauth2"}}
    refused = await client.post(f"/v1/apps/{APP}/accounts", json=body, headers=admin(tenant))
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "setting_not_offered", refused.text


async def test_another_live_account_signs_in_where_the_first_does(client: httpx.AsyncClient, tenant: str) -> None:
    assert (await _turn_on(client, tenant, "https://acme.my.signin.test/oauth2")).status_code == 200
    made = await client.post(f"/v1/apps/{APP}/accounts", json={"name": "Second org"}, headers=admin(tenant))
    assert made.status_code == 201, made.text
    detail = (await client.get(f"/v1/apps/{APP}/accounts/{made.json()['data']['id']}", headers=admin(tenant))).json()
    assert detail["data"]["settings"]["authorizeUrl"] == "https://acme.my.signin.test/oauth2/common/authorize", detail


async def test_the_apps_answer_carries_each_settings_choices_and_typed_host(
    client: httpx.AsyncClient, tenant: str
) -> None:
    page = (await client.get(f"/v1/apps/{APP}", headers=admin(tenant))).json()["data"]
    settings = {s["name"]: s for s in page["card"]["plugin"]["settings"]}
    login = settings["login_url"]
    assert login["label"] == "Where do you sign in?"
    assert [(c["value"], c["label"], c["hint"], c["testAccount"]) for c in login["choices"]] == [
        ("https://login.signin.test/oauth2", "login.signin.test", "Live orgs", False),
        ("https://test.signin.test/oauth2", "test.signin.test", "Orgs used for testing", True),
    ]
    assert login["other"] == {
        "label": "Your company's address",
        "hint": "Your own sign-in host",
        "placeholder": "acme.my.signin.test",
        "value": "https://{host}/oauth2",
        "hosts": [".my.signin.test"],
        "testAccountHosts": [".sandbox.my.signin.test"],
    }
    assert settings["tenant"]["credential"] is True and login["credential"] is False
    assert "choices" not in settings["tenant"] or settings["tenant"]["choices"] is None
