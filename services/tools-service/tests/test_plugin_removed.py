"""A plugin a team turned on and the install then removed, by failure mode: its card vanishes, or turns into a plain
connection the team can edit as if it still worked; its page breaks; and its tools fail with a reason that sends
people to the wrong fix."""

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
from ops_tools.apps import REMOVED
from ops_tools.modules.seed import load
from ops_tools.plugins.host import PluginHost, module_id_of
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings

from .conftest import build_app, response_checker, team_credential
from .plugin_desk import plugin as desk
from .test_plugin_credentials import team_admin
from .test_plugins import ID
from .test_review_decisions import introspect, jwks

Rig = tuple[httpx.AsyncClient, PluginHost]


@pytest.fixture
async def rig(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Rig]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    settings = Settings()
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes),
    )
    store = ConnectionStore(engine)
    host = PluginHost(ModuleStore(engine), PluginBindings(engine), {}, [Loaded("desk", desk, None)], store)
    app = build_app(engine, seed, tenant, auth=auth, plugins=host)
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        yield c, host


async def test_a_removed_plugin_keeps_its_card_and_says_it_is_no_longer_installed(rig: Rig, tenant: str) -> None:
    client, host = rig
    on = await client.put(
        f"/v1/apps/plugin:{ID}/team",
        json={"enabled": True, "credentialId": await team_credential(client, team_admin(tenant), f"plugin:{ID}")},
        headers=team_admin(tenant),
    )
    assert on.status_code == 200, on.text
    conn_id = on.json()["data"]["connectionId"]
    host.loaded = []  # the install's plugins folder no longer holds it
    got = await client.get("/v1/apps", headers=team_admin(tenant))
    cards = got.json()["data"]
    card = next(c for c in cards if c["id"] == f"plugin:{ID}")
    assert card["appState"] == "removed" and "runs Ops AI at your company" in card["appStateReason"], card
    assert card["connectionId"] == conn_id and card["name"] == "Desk"
    assert not [c for c in cards if c["kind"] == "connection" and c["connectionId"] == conn_id], "shown twice"
    page = await client.get(f"/v1/apps/plugin:{ID}", headers=team_admin(tenant))
    assert page.status_code == 200, page.text
    assert page.json()["data"]["card"]["appState"] == "removed"
    rows = page.json()["data"]["accounts"]
    assert rows and all(r["actions"] == [] and r["test"] is None for r in rows), "read-only, with no stale test"


async def test_a_removed_plugins_tool_refuses_with_that_reason(rig: Rig, engine: AsyncEngine, tenant: str) -> None:
    _, host = rig
    module = await ModuleStore(engine).get(tenant, module_id_of(desk.manifest))
    if module is None:
        await host.ensure(tenant, datetime.now(UTC))
        module = await ModuleStore(engine).get(tenant, module_id_of(desk.manifest))
    assert module is not None
    host.loaded = []
    seen = await host.for_call(tenant, "team_platform", module, "live")
    assert "isn't installed, so its tools are off" in str(seen["plugin_off"]), seen


async def test_a_plugin_the_install_does_not_hold_and_the_team_never_had_answers_not_installed(
    rig: Rig, tenant: str
) -> None:
    client, host = rig
    host.loaded = []
    page = await client.get("/v1/apps/plugin:acme.ticketdesk", headers=team_admin(tenant))
    assert page.status_code == 200, page.text
    card = page.json()["data"]["card"]
    assert (card["appState"], card["appStateReason"]) == ("not_installed", REMOVED), card
    assert page.json()["data"]["accounts"] == [] and page.json()["data"]["tools"] == []
    assert (await client.get("/v1/apps/con_unknown", headers=team_admin(tenant))).status_code == 404
    # Only the page reads a missing plugin's card; an auth config for it is refused as an app the team lacks.
    made = await client.post(
        "/v1/app-credentials", json={"app": "plugin:acme.ticketdesk", "clientId": "x"}, headers=team_admin(tenant)
    )
    assert made.status_code == 404, made.text
