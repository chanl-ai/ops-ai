# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The document type templates of the plugins on for a team, from tools-service (c-590), the one service that loads
plugins. Each call carries a service token holding `tools:view` and naming the caller's tenant and team, so
tools-service answers that team's view and never every team's."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import httpx

from ops_documents.files import Who
from ops_identity import ServiceClient
from ops_service_kit.logging import get_logger
from ops_service_kit.settings import Settings

log = get_logger("ops_documents.tools_client")


@dataclass
class PluginTemplates:
    client: ServiceClient

    async def document_types(self, who: Who) -> list[dict[str, Any]]:
        """GET /v1/plugin-templates?kind=document_type as the caller's team; ServiceCallError or ServiceUnreachable
        when tools-service refuses or does not answer."""
        rows = await self.client.get(
            "/v1/plugin-templates", params={"kind": "document_type"}, tenant=who.tenant_id, team=who.team
        )
        return cast(list[dict[str, Any]], rows)


def plugin_templates(settings: Settings) -> PluginTemplates | None:
    """On settings.tools_url; None when it is not set, or there is no service signing key, and the template routes
    answer 503."""
    if not settings.tools_url:
        return None
    http = httpx.AsyncClient(base_url=settings.tools_url, timeout=10)
    try:
        client = ServiceClient.for_settings(
            settings, http, service="documents", audience="tools", scopes=["tools:view"]
        )
    except ValueError as e:  # no service signing key outside dev
        log.warning("no service signing key; plugin templates are not offered", extra={"error": str(e)})
        return None
    return PluginTemplates(client)
