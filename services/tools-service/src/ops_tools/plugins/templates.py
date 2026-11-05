"""`/v1/plugin-templates`: the agents, skills, workflows and document types a plugin brings, as one team sees
them, with each body a copy is made from, and its knowledge sources, which a team adds to a knowledge base.

tools-service is the one service that loads plugins, so agents-service and documents-service read a template's body
here (their service tokens hold `tools:view` and name the team) and make the team's copy through their own create
paths. A plugin's templates are listed only while it is on for the team (the install switch and the team's), the same
rule its tools follow, so a team never copies an agent that grants tools it cannot call. A template's required tools
are answered as the operations the team's plugin module serves.

`/v1/apps/{app}/resources` is the app's Resources tab in one answer: each resource with its state for the team, the
team's copy and whether the caller may add it. agents-service and documents-service keep the copies, so their template
lists are read here (as the caller's team) and joined, and the caller's roles decide each row's `canAdd` over the
roles grid cell the owning service names for it. A knowledge source has no single copy (a team adds it to any of its
knowledge bases), so its row says only whether it can be added now."""

# No `from __future__ import annotations`: FastAPI resolves the `Depends(tools_reader)` annotations at import.

import hashlib
import json
from typing import Annotated, Any, Literal, Protocol, cast

import yaml
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_access import Access
from ops_access.check import granted_by
from ops_identity import Principal, ServiceCallError, ServiceClient, ServiceUnreachable
from ops_plugin_sdk import Plugin
from ops_plugin_sdk.manifest import KnowledgeSource, Template
from ops_service_kit.errors import NotFound, ServiceUnavailable, ValidationFailed
from ops_service_kit.http import Envelope, ok

from ..callers import tools_reader
from ..modules.routes import ERRORS
from .host import PluginHost

Kind = Literal["agent", "skill", "workflow", "document_type", "knowledge_source"]


class TemplateOutside(ValueError):
    """A template's path leads out of its plugin's folder; its file is never read."""


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PluginRef(_Wire):
    id: str
    title: str
    version: str


class TemplateRequires(_Wire):
    # The operations the team's plugin module serves, `<plugin short name>_<tool>`.
    tools: list[str]
    # What the person names at install: `{"knowledge_base": "<what it is>"}` or `{"model_alias": "<capability>"}`.
    bind: list[dict[str, str]]
    # The plugin's other resources a copy cannot run without, each `<source>:<template id>` as the copy route names it.
    resources: list[str] = Field(default_factory=list[str])


class PluginTemplate(_Wire):
    # Where the template comes from, `plugin:<plugin id>`; a built-in pack is another source later.
    source: str
    plugin: PluginRef
    kind: Kind
    id: str
    version: int
    title: str
    requires: TemplateRequires
    # The request body the kind's create route takes (a workflow's is its definition).
    body: dict[str, Any] = Field(default_factory=dict[str, Any])
    # sha256 of the body as canonical JSON: a copy keeps the digest it was made from, so a template whose body changed
    # since then shows as changed even when its version did not move.
    digest: str


def body_of(plugin: Plugin, template: Template) -> dict[str, Any]:
    """The template's body, read only from inside the plugin's folder."""
    root = plugin.root.resolve()
    path = (root / template.path).resolve()
    if root not in path.parents:
        raise TemplateOutside(f"{plugin.manifest.id} template {template.id}: {template.path} is outside the plugin")
    return cast(dict[str, Any], yaml.safe_load(path.read_text()) or {})


def digest_of(body: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def view_of(plugin: Plugin, template: Template) -> dict[str, Any]:
    m = plugin.manifest
    body = body_of(plugin, template)
    return PluginTemplate(
        source=f"plugin:{m.id}",
        plugin=PluginRef(id=m.id, title=m.title, version=m.version),
        kind=template.kind,
        id=template.id,
        version=template.version,
        title=str(body.get("name") or template.id),
        requires=TemplateRequires(
            tools=[m.operation(t) for t in template.requires.tools],
            bind=list(template.requires.bind),
            resources=[f"plugin:{m.id}:{r}" for r in template.requires.resources],
        ),
        body=body,
        digest=digest_of(body),
    ).model_dump(by_alias=True)


def source_view(plugin: Plugin, source: KnowledgeSource) -> dict[str, Any]:
    """A knowledge source as a resource: kb-service makes it, in a knowledge base the team picks, syncing through the
    two tools named here. Its body is the source's definition, so its digest moves when the plugin changes it."""
    m = plugin.manifest
    body = source.model_dump(mode="json")
    return PluginTemplate(
        source=f"plugin:{m.id}",
        plugin=PluginRef(id=m.id, title=m.title, version=m.version),
        kind="knowledge_source",
        id=source.name,
        version=1,
        title=source.title,
        requires=TemplateRequires(
            tools=[m.operation(t) for t in (source.list, source.get)], bind=[{"knowledge_base": source.title}]
        ),
        body=body,
        digest=digest_of(body),
    ).model_dump(by_alias=True)


State = Literal["available", "added", "update_available", "removed_upstream", "needs_sign_in"]
# Which service makes each kind's copy, so a screen sends each add to it.
SERVICES: dict[str, str] = {
    "agent": "agents",
    "skill": "agents",
    "workflow": "agents",
    "document_type": "documents",
    "knowledge_source": "kb",
}
# Who may add a knowledge source: those who may edit the knowledge base it goes into.
KNOWLEDGE_CELL = {"area": "knowledge", "action": "edit"}


class ResourceCopy(_Wire):
    id: str
    kind: str
    record_id: str
    source: str
    template_id: str
    version: int


class ResourceInstalled(_Wire):
    copies: int
    version: int | None
    newer_available: bool
    changed: bool = False


class AppResource(_Wire):
    source: str
    plugin: PluginRef
    kind: Kind
    id: str
    version: int
    title: str
    requires: TemplateRequires
    # The copies the team holds; None for a knowledge source, which has no single copy.
    installed: ResourceInstalled | None = None
    # available, added, update_available, removed_upstream (the team holds a copy the app no longer ships), or
    # needs_sign_in (a knowledge source of an app whose team account is not signed in: its syncs run as that account).
    state: State
    can_add: bool
    # Why the caller cannot add it, in words naming who can; None when they can.
    reason: str | None = None
    # The team's copy, which Open, Remove and an update act on.
    copy_: ResourceCopy | None = Field(default=None, alias="copy")
    # The service that makes the copy: agents, documents or kb.
    service: str


class Copies(Protocol):
    """The template lists of the services that keep copies, as the caller's team sees them."""

    async def of(self, tenant_id: str, team_id: str, source: str) -> list[dict[str, Any]]: ...


class ServiceCopies:
    """agents-service's `GET /v1/templates?source=` and documents-service's `GET /v1/templates`, each read with a
    service token naming the caller's team."""

    def __init__(self, agents: ServiceClient, documents: ServiceClient) -> None:
        self.agents, self.documents = agents, documents

    async def of(self, tenant_id: str, team_id: str, source: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name, client, params in (
            ("agents-service", self.agents, {"source": source}),
            ("documents-service", self.documents, None),
        ):
            try:
                rows = cast(
                    list[dict[str, Any]],
                    await client.get("/v1/templates", params=params, tenant=tenant_id, team=team_id),
                )
            except (ServiceCallError, ServiceUnreachable) as e:
                raise ServiceUnavailable(
                    f"{name} did not answer with the team's copies of this app's resources. Try again shortly.",
                    code="resources_unavailable",
                ) from e
            out += [r for r in rows if r.get("source") == source]
        return out


def who_adds(area: str, action: str) -> str:
    """Who adds a resource, in words: the narrowest role the grid gives the cell, "A builder adds this."."""
    roles = granted_by(area, action)
    who = roles[0].name.lower() if roles else "nobody in the team"
    return f"{'An' if who[0] in 'aeiou' else 'A'} {who} adds this."


def plugin_templates_router(host: PluginHost, copies: Copies | None = None) -> APIRouter:
    r = APIRouter(tags=["plugins"], responses=ERRORS)
    access = Access()

    async def needs_sign_in(tenant_id: str, team_id: str, plugin: Plugin) -> bool:
        """Whether the app's syncs would run as no one: it signs in, and its team account is not connected."""
        if set(plugin.manifest.connection.kinds) <= {"none"}:
            return False
        b = await host.bindings.get(tenant_id, team_id, plugin.manifest.id) or {}
        if not b.get("connection_id") or host.connections is None:
            return True
        conn = await host.connections.get(tenant_id, str(b["connection_id"]))
        return (conn or {}).get("status") != "connected"

    @r.get("/v1/apps/{app_id}/resources", response_model=Envelope[list[AppResource]])
    async def list_app_resources(  # pyright: ignore[reportUnusedFunction]
        app_id: str, who: Annotated[Principal, Depends(tools_reader)]
    ) -> JSONResponse:
        """The app's Resources tab: every agent, skill, workflow, document type and knowledge source the app brings,
        and every copy the team holds of one it no longer ships or of an app turned off, each with its state, the
        team's copy, and whether the caller may add it (with who can, when they cannot)."""
        if not who.team_id:
            raise ValidationFailed("Resources are listed for one team; this call names none.", code="team_required")
        plugin = host.plugins.get(app_id.removeprefix("plugin:")) if app_id.startswith("plugin:") else None
        if plugin is None:
            raise NotFound(f"An app {app_id} with resources")
        if copies is None:
            raise ServiceUnavailable("This service has no address for the services that keep copies.")
        m = plugin.manifest
        out: list[dict[str, Any]] = []
        for row in await copies.of(who.tenant_id, who.team_id, app_id):
            cell = cast(dict[str, str], row.get("addCell") or {})
            held = row.get("state") != "available"
            may = row.get("state") != "removed_upstream" and access.may(who, cell["area"], cell["action"])
            view = {k: row[k] for k in ("source", "kind", "id", "version", "title", "requires", "installed", "copy")}
            out.append(
                AppResource.model_validate(
                    view
                    | {
                        "plugin": {"id": m.id, "title": m.title, "version": m.version},
                        "state": row["state"],
                        "canAdd": may and not held,
                        "reason": None if may or held else who_adds(cell["area"], cell["action"]),
                        "service": SERVICES[str(row["kind"])],
                    }
                ).model_dump(by_alias=True)
            )
        if m.knowledge_sources and await host.off_reason(who.tenant_id, who.team_id, plugin) is None:
            signed_out = await needs_sign_in(who.tenant_id, who.team_id, plugin)
            may = access.may(who, KNOWLEDGE_CELL["area"], KNOWLEDGE_CELL["action"])
            for s in m.knowledge_sources:
                view = {k: v for k, v in source_view(plugin, s).items() if k not in ("body", "digest")}
                out.append(
                    AppResource.model_validate(
                        view
                        | {
                            "state": "needs_sign_in" if signed_out else "available",
                            "canAdd": may and not signed_out,
                            "reason": None if may else who_adds(KNOWLEDGE_CELL["area"], KNOWLEDGE_CELL["action"]),
                            "service": "kb",
                        }
                    ).model_dump(by_alias=True)
                )
        return ok(out)

    @r.get("/v1/plugin-templates", response_model=Envelope[list[PluginTemplate]])
    async def list_plugin_templates(  # pyright: ignore[reportUnusedFunction]
        who: Annotated[Principal, Depends(tools_reader)], kind: Annotated[Kind | None, Query()] = None
    ) -> JSONResponse:
        """Every template and knowledge source of every plugin on for the caller's team, with its body. A person in the
        team, or a service holding `tools:view` that names the team, may read it; a call naming no team is refused,
        since templates are listed per team."""
        if not who.team_id:
            raise ValidationFailed("Templates are listed for one team; this call names none.", code="team_required")
        out: list[dict[str, Any]] = []
        for plugin in host.plugins.values():
            m = plugin.manifest
            if not (m.templates or m.knowledge_sources):
                continue
            if await host.off_reason(who.tenant_id, who.team_id, plugin) is not None:
                continue
            out += [view_of(plugin, t) for t in m.templates if kind in (None, t.kind)]
            out += [source_view(plugin, s) for s in m.knowledge_sources if kind in (None, "knowledge_source")]
        return ok(out)

    return r


__all__ = [
    "AppResource",
    "Copies",
    "PluginTemplate",
    "ServiceCopies",
    "TemplateOutside",
    "body_of",
    "digest_of",
    "plugin_templates_router",
    "source_view",
    "view_of",
]
