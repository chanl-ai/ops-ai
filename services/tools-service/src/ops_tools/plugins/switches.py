"""The install switch: which installed plugins the platform admin turned off, and the fields they locked (c-564).

It is platform-service's `plugins` workspace policy ({plugin id: {enabled, locked}}), which only a holder of
settings.manage in the Security team may change. An installed plugin is on unless its entry says `enabled: false`:
installing it is the decision to offer it. tools-service reads the policy with its own `settings:view` token and keeps
it FRESH_S seconds, so turning a plugin off reaches every call within that time and needs no restart. A read that fails
keeps the last answer read; with none, every plugin counts as off, so an outage never runs a plugin an admin stopped.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol, cast

from ops_identity import ServiceCallError, ServiceUnreachable

FRESH_S = 5.0


class Platform(Protocol):
    async def get(self, path: str, *, tenant: str) -> Any: ...


class InstallSwitches:
    def __init__(
        self,
        platform: Platform | None,
        *,
        dev: dict[str, Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """`dev` is the value used with no platform-service (dev sign-in)."""
        self.platform = platform
        self.dev = dev
        self.clock = clock
        self._kept: dict[str, tuple[float, dict[str, Any]]] = {}

    async def _value(self, tenant_id: str) -> dict[str, Any] | None:
        """The policy's value; None when it cannot be read and was never read."""
        if self.platform is None:
            return dict(self.dev or {})
        kept = self._kept.get(tenant_id)
        if kept is not None and self.clock() - kept[0] < FRESH_S:
            return kept[1]
        try:
            data = await self.platform.get("/v1/policies/plugins", tenant=tenant_id)
            value = dict(data.get("value") or {})
        except (ServiceCallError, ServiceUnreachable, KeyError, TypeError, ValueError, AttributeError):
            return kept[1] if kept is not None else None
        self._kept[tenant_id] = (self.clock(), value)
        return value

    async def _entry(self, tenant_id: str, plugin_id: str) -> dict[str, Any]:
        entry = (await self._value(tenant_id) or {}).get(plugin_id)
        return cast(dict[str, Any], entry) if isinstance(entry, dict) else {}

    async def on(self, tenant_id: str, plugin_id: str) -> bool:
        if self.platform is None and self.dev is None:
            return True
        value = await self._value(tenant_id)
        if value is None:
            return False
        entry = value.get(plugin_id)
        return not (isinstance(entry, dict) and cast(dict[str, Any], entry).get("enabled") is False)

    async def locked(self, tenant_id: str, plugin_id: str) -> dict[str, Any]:
        return dict(cast(dict[str, Any], (await self._entry(tenant_id, plugin_id)).get("locked") or {}))
