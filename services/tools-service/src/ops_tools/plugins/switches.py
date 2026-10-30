"""The install switch: which plugins the platform admin turned on for the install, and the fields they locked (c-564).

It is platform-service's `plugins` workspace policy ({plugin id: {enabled, locked}}), which only a holder of
settings.manage in the Security team may change. tools-service reads it with its own `settings:view` token and keeps
it FRESH_S seconds, so turning a plugin off reaches every call within that time and needs no restart. A policy that
cannot be read counts as every plugin off, so a failed read never runs a plugin the admin may have stopped."""

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
        """`dev` is the value used with no platform-service (dev sign-in): every plugin on, unless it says otherwise."""
        self.platform = platform
        self.dev = dev
        self.clock = clock
        self._kept: dict[str, tuple[float, dict[str, Any]]] = {}

    async def _value(self, tenant_id: str) -> dict[str, Any]:
        if self.platform is None:
            return dict(self.dev or {})
        kept = self._kept.get(tenant_id)
        if kept is not None and self.clock() - kept[0] < FRESH_S:
            return kept[1]
        try:
            data = await self.platform.get("/v1/policies/plugins", tenant=tenant_id)
            value = dict(data.get("value") or {})
        except (ServiceCallError, ServiceUnreachable, KeyError, TypeError, ValueError, AttributeError):
            value = {}
        self._kept[tenant_id] = (self.clock(), value)
        return value

    async def _entry(self, tenant_id: str, plugin_id: str) -> dict[str, Any]:
        entry = (await self._value(tenant_id)).get(plugin_id)
        return cast(dict[str, Any], entry) if isinstance(entry, dict) else {}

    async def on(self, tenant_id: str, plugin_id: str) -> bool:
        if self.platform is None and self.dev is None:
            return True
        return (await self._entry(tenant_id, plugin_id)).get("enabled") is True

    async def app_client_id(self, tenant_id: str, plugin_id: str) -> str | None:
        """The client id of the platform's own OAuth app for the plugin (c-565), when the platform admin set one."""
        client = (await self._entry(tenant_id, plugin_id)).get("client")
        cid = cast(dict[str, Any], client).get("id") if isinstance(client, dict) else None
        return cid if isinstance(cid, str) and cid else None

    async def locked(self, tenant_id: str, plugin_id: str) -> dict[str, Any]:
        return dict(cast(dict[str, Any], (await self._entry(tenant_id, plugin_id)).get("locked") or {}))
