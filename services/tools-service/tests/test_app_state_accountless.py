"""A template pack (a plugin with no endpoint, such as the built-in core case types) has no account to sign in, so
turning it on is all it takes: its card reads connected once on and off once off, never needing a sign-in or an
account it can never have. Rig: test_app_accounts, with the built-in core pack loaded beside the desk plugin."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_plugin_sdk import Plugin
from ops_plugin_sdk.loader import Loaded
from ops_service_kit.settings import Settings
from ops_tools.modules.seed import load
from ops_tools.plugins.host import PluginHost
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings

from .conftest import build_app
from .test_app_accounts import admin
from .test_plugin_credentials import INSTALL
from .test_review_decisions import introspect, jwks

CORE = Plugin.beside(str(Path(__file__).resolve().parents[3] / "builtin-plugins/ops_plugin_core/__init__.py"))
APP = f"plugin:{CORE.manifest.id}"


@pytest.fixture
async def client(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[httpx.AsyncClient]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    settings = Settings()
    services = ServiceAuth(
        audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes
    )
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0, services=services), services
    )
    store = ConnectionStore(engine, INSTALL)
    host = PluginHost(ModuleStore(engine), PluginBindings(engine), {}, [Loaded("core", CORE, None)], store)
    app = build_app(engine, seed, tenant, auth=auth, install_clients=INSTALL, plugins=host)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c:
        yield c


async def state(c: httpx.AsyncClient, tenant: str) -> str:
    r = await c.get("/v1/apps", headers=admin(tenant))
    assert r.status_code == 200, r.text
    return next(x for x in r.json()["data"] if x["id"] == APP)["appState"]


async def test_a_template_pack_turned_on_reads_connected_and_off_again_when_turned_off(
    client: httpx.AsyncClient, tenant: str
) -> None:
    assert await state(client, tenant) == "off"
    on = await client.put(f"/v1/apps/{APP}/team", json={"enabled": True, "sandbox": False}, headers=admin(tenant))
    assert on.status_code == 200, on.text
    assert on.json()["data"]["connectionId"] is None
    assert await state(client, tenant) == "connected"
    off = await client.put(f"/v1/apps/{APP}/team", json={"enabled": False, "sandbox": False}, headers=admin(tenant))
    assert off.status_code == 200, off.text
    assert await state(client, tenant) == "off"
