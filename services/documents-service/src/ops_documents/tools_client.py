# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The document type templates of the plugins on for a team, from tools-service, the one service that loads
plugins. Each call carries a service token holding `tools:view` and naming the caller's tenant and team, so
tools-service answers that team's view and never every team's."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NotRequired, TypedDict

from ops_documents.files import Who
from ops_identity import ServiceClient
from ops_service_kit.http import Json
from ops_service_kit.logging import get_logger
from ops_service_kit.narrow import a_list
from ops_service_kit.settings import Settings
from ops_store.documents import stored

log = get_logger("ops_documents.tools_client")


class TemplatePluginRef(TypedDict):
    id: str
    title: str
    version: str


class OfferedTemplate(TypedDict):
    """One resource of `GET /v1/plugin-templates`, as tools-service's `PluginTemplate` sends it; the keys this service
    reads are declared, and any other key stays in the view."""

    source: str
    plugin: TemplatePluginRef
    kind: str
    id: str
    version: int
    title: str
    requires: Json
    # The kind's create body, and the digest a copy keeps; read with `.get`, as an older tools-service sends neither.
    body: NotRequired[Json]
    digest: NotRequired[str | None]


OFFERED = stored(OfferedTemplate)


@dataclass
class PluginTemplates:
    client: ServiceClient

    async def offered(self, who: Who) -> list[OfferedTemplate]:
        """GET /v1/plugin-templates as the caller's team: every resource of the apps on for it, of every kind, so a
        copy whose app still ships other resources but not its own reads as removed by the app. ServiceCallError or
        ServiceUnreachable when tools-service refuses or does not answer; an answer that is not a list of templates
        fails the call."""
        rows = await self.client.get("/v1/plugin-templates", tenant=who.tenant_id, team=who.team)
        return [OFFERED(r) for r in a_list(rows, "tools-service's templates")]


def plugin_templates(settings: Settings) -> PluginTemplates | None:
    """On the tools endpoint, with its timeout; None when it is not set, or there is no service signing key, and the
    template routes answer 503."""
    if settings.tools is None:
        return None
    try:
        client = ServiceClient.for_settings(settings, service="documents", audience="tools", scopes=["tools:view"])
    except ValueError as e:  # no service signing key outside dev
        log.warning("no service signing key; plugin templates are not offered", extra={"error": str(e)})
        return None
    return PluginTemplates(client)
