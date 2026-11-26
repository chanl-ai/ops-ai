# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Find places: what a person can pick to read from (a site, a library, a folder), asked of the source's scopes tool
as the team's connection. The knowledge wizard's picker and Files' watched folders ask it the same way."""

from __future__ import annotations

from ops_service_kit.errors import ServiceUnavailable, ValidationFailed
from ops_service_kit.http import JsonValue

from .contract import Declared, FoundPlace, places_of
from .state import Reader


async def find_places(
    reader: Reader,
    tenant: str,
    team: str,
    found: Declared,
    *,
    query: str | None = None,
    parent: str | None = None,
    cursor: str | None = None,
    act: str,
) -> tuple[list[FoundPlace], str | None]:
    """The places matching `query`, or those `parent` holds, one page at a time, with the next page's cursor. Refused
    for a source with nothing to pick; a source that fails to answer is said as unavailable, with its reason."""
    if not found.scopesTool:
        raise ValidationFailed(f"{found.title} has nothing to pick.", code="scopes_unavailable")
    given: dict[str, JsonValue] = {
        k: v for k, v in (("query", query), ("parent", parent), ("cursor", cursor)) if v not in (None, "")
    }
    answer = await reader.call(tenant, team, found.scopesTool, given, act=act)
    if not answer.ok:
        raise ServiceUnavailable(
            f"The picker could not ask {found.title}: {answer.message or answer.code}", code="scopes_failed"
        )
    return places_of(answer.output)
