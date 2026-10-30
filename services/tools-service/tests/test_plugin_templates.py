"""A plugin's templates as a team sees them (c-590), through the real route, by failure mode: a team whose plugin is off
sees its templates anyway, so it could install copies that use tools it cannot call; a team sees another plugin's or
nothing at all once its plugin is on; a template's body is missing, so agents-service and documents-service have
nothing to make the copy from; a required tool is named as the plugin's short name, not the operation the team's
module serves; a call naming no team gets every team's view; and a body path outside the plugin folder is read.

The test plugin is tests/plugin_templates/templates_desk, loaded the way OPS_PLUGIN_PATHS loads a developer's plugin."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity, dev_service_signer, mint_service_token
from ops_plugin_sdk import Plugin
from ops_plugin_sdk.loader import discover
from ops_service_kit.settings import Settings
from ops_tools.plugins.host import PluginHost
from ops_tools.plugins.switches import InstallSwitches
from ops_tools.plugins.templates import TemplateOutside, body_of, plugin_templates_router
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings

from .conftest import build_app, response_checker
from .test_plugins import Policy
from .test_review_decisions import introspect, jwks, person

ON, OFF = "team_platform", "team_ops"
PLUGIN = "test.templates"
FOLDER = Path(__file__).parent / "plugin_templates" / "templates_desk"


@pytest.fixture
async def client(engine: AsyncEngine, seed: dict[str, Any], tenant: str) -> AsyncIterator[httpx.AsyncClient]:
    loaded = discover(found=[], folders=[str(FOLDER)])
    assert all(item.ok for item in loaded), [item.error for item in loaded if not item.ok]
    host = PluginHost(
        ModuleStore(engine), PluginBindings(engine), InstallSwitches(Policy({PLUGIN: {"enabled": True}})), loaded
    )
    bindings = PluginBindings(engine)
    await bindings.put(tenant, ON, PLUGIN, enabled=True, connection_id=None, settings={}, by="test")
    await bindings.put(tenant, OFF, PLUGIN, enabled=False, connection_id=None, settings={}, by="test")
    # People sign in with the platform's tokens; services with the dev service key, as the tools tests sign them.
    dev = Auth.for_dev(Settings(), audience="tools", name="dev", email="dev", tenant_id=tenant)
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0, services=dev.services), dev.services
    )
    app = build_app(engine, seed, tenant, auth=auth)
    app.include_router(plugin_templates_router(host))
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        yield c


def service(tenant: str, team: str | None, name: str = "agents", scopes: list[str] | None = None) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(),
        service=name,
        audience="tools",
        tenant_id=tenant,
        team_id=team,
        scopes=scopes if scopes is not None else ["tools:view"],
    )
    return {"Authorization": f"Bearer {token}"}


async def listed(c: httpx.AsyncClient, headers: dict[str, str], **params: str) -> list[dict[str, Any]]:
    r = await c.get("/v1/plugin-templates", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return list(r.json()["data"])


async def test_a_team_sees_the_templates_only_while_the_plugin_is_on_for_it(
    client: httpx.AsyncClient, tenant: str
) -> None:
    on = await listed(client, person(tenant, "Priya Shah", {ON: "builder"}))
    off = await listed(client, person(tenant, "Maya Okafor", {OFF: "builder"}))
    assert sorted((t["kind"], t["id"]) for t in on) == [
        ("agent", "case-helper"),
        ("document_type", "case-letter"),
        ("skill", "close-politely"),
        ("workflow", "case-review"),
    ]
    assert off == []


async def test_each_template_carries_its_body_source_version_and_the_teams_operations(
    client: httpx.AsyncClient, tenant: str
) -> None:
    [agent] = await listed(client, service(tenant, ON), kind="agent")
    assert agent["source"] == f"plugin:{PLUGIN}"
    assert agent["plugin"] == {"id": PLUGIN, "title": "Case desk", "version": "0.2.0"}
    assert agent["version"] == 2 and agent["title"] == "Case helper"
    assert agent["body"]["role"].startswith("Reads a case")
    # The tools are the operations the team's plugin module serves, so the copy grants what the gateway calls.
    assert agent["requires"]["tools"] == ["templates_get_case", "templates_close_case"]
    assert agent["requires"]["bind"] == [{"knowledge_base": "Case articles"}, {"model_alias": "chat"}]
    # The digest is the body's fingerprint: a copy keeps it, so a changed template shows as changed since install.
    body = json.dumps(agent["body"], sort_keys=True, separators=(",", ":")).encode()
    assert agent["digest"] == hashlib.sha256(body).hexdigest()
    [workflow] = await listed(client, service(tenant, ON), kind="workflow")
    assert workflow["body"]["schemaVersion"] == 2 and workflow["body"]["id"] == "case_review"


async def test_a_call_naming_no_team_or_without_tools_view_is_refused(client: httpx.AsyncClient, tenant: str) -> None:
    # The identity layer refuses a service token naming no team before the route runs; the route refuses any other
    # caller with no team, so no call gets every team's view.
    no_team = await client.get("/v1/plugin-templates", headers=service(tenant, None))
    assert no_team.status_code == 403 and no_team.json()["error"]["code"] == "team_required", no_team.text
    unscoped = await client.get("/v1/plugin-templates", headers=service(tenant, ON, "documents", scopes=[]))
    assert unscoped.status_code == 403, unscoped.text


def test_a_body_outside_the_plugin_folder_is_never_read(tmp_path: Path) -> None:
    plugin = Plugin.beside(str(FOLDER / "__init__.py"))
    [agent] = [t for t in plugin.manifest.templates if t.kind == "agent"]
    escaped = agent.model_copy(update={"path": "../../../conftest.py"})
    with pytest.raises(TemplateOutside):
        body_of(plugin, escaped)
