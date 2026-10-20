"""Workspace policies read live from platform-service (`GET /v1/policies/{key}`) through `ServiceClient`, for the
current tenant. Read on every call, never cached, for a policy whose change must apply at once (publishReview,
c-214). A read that fails raises PolicyUnread, so each caller decides what an unread policy means for it; so does a
process with no service signing key (no client), which still starts."""

from __future__ import annotations

from typing import Any, Protocol, cast

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable


class PolicyUnread(Exception):
    """platform-service did not answer the policy."""


class PolicySource(Protocol):
    async def value(self, key: str) -> Any:
        """The current tenant's value for `key`; raises PolicyUnread when it cannot be read."""
        ...


class PlatformPolicies:
    def __init__(self, platform: ServiceClient | None) -> None:
        self.platform = platform

    async def value(self, key: str) -> Any:
        if self.platform is None:
            raise PolicyUnread(f"{key}: no service signing key to read platform-service with")
        try:
            data = await self.platform.get(f"/v1/policies/{key}")
        except (ServiceCallError, ServiceUnreachable) as e:
            raise PolicyUnread(f"{key}: {e}") from e
        return cast(dict[str, Any], data or {}).get("value")
