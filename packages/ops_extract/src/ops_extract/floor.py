"""The workspace floor for extracted fields (c-157): platform-service's `extractionFloor` policy (Govern > Policies),
which no extraction goes below. The caller reads it per extraction with its own service token for the tenant, so a
change applies to the next extraction. A floor that cannot be read stops the step rather than falling back to
the default: a failed read must never lower the bar a field has to clear."""

from __future__ import annotations

from typing import Any, cast

from ops_extract.checks import DEFAULT_FLOOR
from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable

POLICY = "extractionFloor"


class FloorUnreadError(RuntimeError):
    """The policy could not be read, or holds something that is not a confidence between 0 and 1."""


class PlatformFloor:
    """The workspace floor on platform-service; the engine's SettingsPort and files-service's extraction read it."""

    def __init__(self, platform: ServiceClient | None) -> None:
        self.platform = platform

    async def extraction_floor(self) -> float:
        if self.platform is None:
            raise FloorUnreadError(f"The {POLICY} policy could not be read: no service signing key")
        try:
            value: Any = cast(dict[str, Any], await self.platform.get(f"/v1/policies/{POLICY}") or {}).get("value")
        except (ServiceCallError, ServiceUnreachable) as e:
            raise FloorUnreadError(f"The {POLICY} policy could not be read: {e}") from e
        if value is None:
            return DEFAULT_FLOOR  # cleared in Govern > Policies: the catalogue's default
        # bool is an int in Python; a switch value is not a confidence.
        if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 1:
            raise FloorUnreadError(f"The {POLICY} policy holds {value!r}, not a confidence between 0 and 1.")
        return float(value)
