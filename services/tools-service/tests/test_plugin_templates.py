"""A plugin's templates as a team sees them, through the real route, by failure mode: a team whose plugin is off
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
from ops_tools.plugins.templates import TemplateOutside, body_of, plugin_templates_router
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings

from .conftest import build_app, response_checker
from .test_review_decisions import introspect, jwks, person

ON, OFF = "team_platform", "team_ops"
PLUGIN = "test.templates"
FOLDER = Path(__file__).parent / "plugin_templates" / "templates_desk"


# A second plugin whose workflow runs its own agent and which brings a knowledge source, written per test.
LINKED = "test.linked"
LINKED_MANIFEST = """\
schema: ops-ai/plugin@2
id: test.linked
title: Linked desk
version: 0.1.0
sdk: "1"
connection: { kinds: [none], sign_in: [team] }
egress: ["https://api.linked.test"]
endpoint: "https://api.linked.test"
tools:
  - { name: get_case, access: read, input: { id: { type: string } }, request: { method: GET, path: "/cases/{id}" } }
  - name: list_articles
    access: read
    knowledge: list_items
    input: { since: { type: string, required: false }, cursor: { type: string, required: false } }
    request: { method: GET, path: "/articles" }
  - name: get_article
    access: read
    knowledge: get_item
    input: { id: { type: string } }
    request: { method: GET, path: "/articles/{id}" }
knowledge_sources:
  - { name: articles, title: Help articles, list: list_articles, get: get_article }
templates:
  - { kind: agent, id: helper, version: 1, path: helper.yaml, requires: { tools: [get_case] } }
  - { kind: workflow, id: triage, version: 1, path: triage.yaml, requires: { tools: [get_case], resources: [helper] } }
"""


def linked_desk(parent: Path) -> Path:
    root = parent / "linked_desk"
    root.mkdir()
    (root / "__init__.py").write_text("from ops_plugin_sdk import Plugin\n\nplugin = Plugin.beside(__file__)\n")
    (root / "plugin.yaml").write_text(LINKED_MANIFEST)
    (root / "helper.yaml").write_text("name: Helper\ninstructions: Help.\n")
    (root / "triage.yaml").write_text("schemaVersion: 2\nid: triage\nname: Triage\nnodes: []\nconnections: []\n")
    return root


@pytest.fixture
async def client(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    loaded = discover(found=[], folders=[str(FOLDER), str(linked_desk(tmp_path))])
    assert all(item.ok for item in loaded), [item.error for item in loaded if not item.ok]
    host = PluginHost(ModuleStore(engine), PluginBindings(engine), {}, loaded)
    bindings = PluginBindings(engine)
    await bindings.put(tenant, ON, PLUGIN, enabled=True, connection_id=None, settings={}, by="test")
    await bindings.put(tenant, OFF, PLUGIN, enabled=False, connection_id=None, settings={}, by="test")
    await bindings.put(tenant, ON, LINKED, enabled=True, connection_id=None, settings={}, by="test")
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
    on = [t for t in await listed(client, person(tenant, "Priya Shah", {ON: "builder"})) if t["plugin"]["id"] == PLUGIN]
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
    [agent] = [t for t in await listed(client, service(tenant, ON), kind="agent") if t["plugin"]["id"] == PLUGIN]
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
    [workflow] = [t for t in await listed(client, service(tenant, ON), kind="workflow") if t["plugin"]["id"] == PLUGIN]
    assert workflow["body"]["schemaVersion"] == 2 and workflow["body"]["id"] == "case_review"


async def test_a_call_naming_no_team_or_without_tools_view_is_refused(client: httpx.AsyncClient, tenant: str) -> None:
    # The identity layer refuses a service token naming no team before the route runs; the route refuses any other
    # caller with no team, so no call gets every team's view.
    no_team = await client.get("/v1/plugin-templates", headers=service(tenant, None))
    assert no_team.status_code == 403 and no_team.json()["error"]["code"] == "team_required", no_team.text
    unscoped = await client.get("/v1/plugin-templates", headers=service(tenant, ON, "documents", scopes=[]))
    assert unscoped.status_code == 403, unscoped.text


async def test_a_workflow_names_the_resources_it_needs_and_a_knowledge_source_is_a_resource(
    client: httpx.AsyncClient, tenant: str
) -> None:
    mine = {t["id"]: t for t in await listed(client, service(tenant, ON)) if t["plugin"]["id"] == LINKED}
    # Named as the copy route names a resource, so a preview and an add find the team's copy of it.
    assert mine["triage"]["requires"]["resources"] == [f"plugin:{LINKED}:helper"]
    assert mine["helper"]["requires"]["resources"] == []
    articles = mine["articles"]
    assert articles["kind"] == "knowledge_source" and articles["title"] == "Help articles"
    assert articles["requires"]["tools"] == ["linked_list_articles", "linked_get_article"]
    assert articles["requires"]["bind"] == [{"knowledge_base": "Help articles"}]
    only = await listed(client, service(tenant, ON), kind="knowledge_source")
    assert [t["id"] for t in only] == ["articles"]


def test_a_body_outside_the_plugin_folder_is_never_read(tmp_path: Path) -> None:
    plugin = Plugin.beside(str(FOLDER / "__init__.py"))
    [agent] = [t for t in plugin.manifest.templates if t.kind == "agent"]
    escaped = agent.model_copy(update={"path": "../../../conftest.py"})
    with pytest.raises(TemplateOutside):
        body_of(plugin, escaped)
