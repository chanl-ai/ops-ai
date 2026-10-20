"""API keys as the Channels list shows them (c-246): platform-service holds the keys, agents-service counts what each
started. Read through ServiceClient on every list, since a key revoked a moment ago must not stay green; None when the
keys cannot be read, and the list then has no API rows."""

from __future__ import annotations

from typing import Any, cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.logging import get_logger

log = get_logger("ops_agents.key_summaries")


class PlatformKeySummaries:
    def __init__(self, platform: ServiceClient | None) -> None:
        self.platform = platform

    async def list(self) -> list[dict[str, Any]] | None:
        if self.platform is None:
            return None
        try:
            return cast(list[dict[str, Any]], await self.platform.get("/v1/api-key-summaries") or [])
        except (ServiceCallError, ServiceUnreachable) as e:
            log.warning("API keys unread; the Channels list shows none", extra={"error": str(e)})
            return None
