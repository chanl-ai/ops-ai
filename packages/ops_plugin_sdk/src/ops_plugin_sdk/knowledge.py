"""The knowledge-source contract's shared rules: which source a tool serves, and the hosts a source's own settings
let its calls reach. tools-service and the test kit both use these, so a plugin tested here is reached the same way in
production."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
from urllib.parse import urlsplit

from .manifest import KnowledgeSource, Manifest


def source_of(manifest: Manifest, tool: str) -> KnowledgeSource | None:
    """The knowledge source whose list, get, changes, deleted or scopes tool `tool` is; None for any other tool."""
    return next((s for s in manifest.knowledge_sources if tool in {n for _, n in s.tools()}), None)


def source_hosts(source: KnowledgeSource, values: Mapping[str, Any] | None) -> list[str]:
    """The hosts of the addresses a source's `egress_from` input holds (a URL or a list of them), lower case; none
    when the source declares no `egress_from` or the call carries no values. Whether each host may be reached is still
    the egress policy's: a private or link-local address is refused unless the account allows it."""
    if source.egress_from is None or not values:
        return []
    given = values.get(source.egress_from)
    addresses: list[Any] = cast(list[Any], given) if isinstance(given, list) else [given]
    out: list[str] = []
    for a in addresses:
        host = urlsplit(str(a)).hostname if a else None
        if host and host.lower() not in out:
            out.append(host.lower())
    return out
