"""`/v1/plugin-templates`: the agents, skills, workflows and document types a plugin brings, as one team sees
them, with each body a copy is made from, and its knowledge sources, which a team adds to a knowledge base.

tools-service is the one service that loads plugins, so agents-service and documents-service read a template's body
here (their service tokens hold `tools:view` and name the team) and make the team's copy through their own create
paths. A plugin's templates are listed only while it is on for the team (the install switch and the team's), the same
rule its tools follow, so a team never copies an agent that grants tools it cannot call. A template's required tools
are answered as the operations the team's plugin module serves."""

# No `from __future__ import annotations`: FastAPI resolves the `Depends(tools_reader)` annotations at import.

import hashlib
import json
from typing import Annotated, Any, Literal, cast

import yaml
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_identity import Principal
from ops_plugin_sdk import Plugin
from ops_plugin_sdk.manifest import KnowledgeSource, Template
from ops_service_kit.errors import ValidationFailed
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


def plugin_templates_router(host: PluginHost) -> APIRouter:
    r = APIRouter(tags=["plugins"], responses=ERRORS)

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
    "PluginTemplate",
    "TemplateOutside",
    "body_of",
    "digest_of",
    "plugin_templates_router",
    "source_view",
    "view_of",
]
