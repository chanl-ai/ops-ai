# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Which of a team's workflows read a document type, from agents-service, which keeps workflows: a type's delete is
refused while any does. Each call carries a service token holding `workflows:view` and naming the caller's team."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from ops_documents.files import Who
from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.errors import ServiceUnavailable
from ops_service_kit.narrow import an_object, entries
from ops_service_kit.settings import Settings


@dataclass
class TypeUses:
    client: ServiceClient

    async def of(self, who: Who, type_id: str) -> list[dict[str, str]]:
        """The workflows that read the type, each `{kind, id, name}`; 503 when agents-service does not answer, since a
        delete it cannot check is not made."""
        try:
            found = await self.client.get(
                "/v1/document-type-uses", params={"types": type_id}, tenant=who.tenant_id, team=who.team
            )
        except (ServiceCallError, ServiceUnreachable) as e:
            raise ServiceUnavailable(
                "agents-service did not say which workflows read this document type; try again shortly.",
                code="type_uses_unavailable",
            ) from e
        # A guard: an answer that is not an object fails the call, so no delete is made unchecked.
        uses = an_object(found, "agents-service's type uses").get(type_id)
        return cast(list[dict[str, str]], [*entries(uses)])


def type_uses(settings: Settings) -> TypeUses | None:
    """On the agents endpoint; None when there is no service signing key."""
    try:
        return TypeUses(
            ServiceClient.for_settings(settings, service="documents", audience="agents", scopes=["workflows:view"])
        )
    except ValueError:  # no service signing key outside dev
        return None
