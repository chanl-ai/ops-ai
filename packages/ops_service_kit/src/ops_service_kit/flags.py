"""Feature flags: the install's switches for features not yet fully released.

Every flag is off unless the install config names it in `OPS_FLAGS` (Settings.flags); there is no admin screen and no
flag server. Services read a flag through `Settings.feature_flags`, and the console reads platform-service's
`GET /v1/flags`. A flag is deleted, with the check behind it, by the release that fully ships its feature
(docs/deploy/install.md, "Feature flags").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# The names, as a type, so the platform answer's schema and the console's generated types carry them; a test keeps
# this and FLAGS equal.
FlagName = Literal["mcp_gateway", "tool_search", "plugin_updates"]


@dataclass(frozen=True)
class Flag:
    name: FlagName
    # One line, said to an operator reading the flags answer.
    description: str
    remove_when: str


FLAGS: tuple[Flag, ...] = (
    Flag(
        name="mcp_gateway",
        description="Outside assistants reach a team's tools at the MCP address (/mcp/{env}/{team}).",
        remove_when="Outside assistants over MCP are released to every install.",
    ),
    Flag(
        name="tool_search",
        description="Agents with more tools than OPS_TOOL_SEARCH_ABOVE search for the one they need.",
        remove_when="Tool search is released to every install.",
    ),
    Flag(
        name="plugin_updates",
        description="Each team keeps the plugin version it took and reviews an upgrade before its tools change.",
        remove_when="Plugin updates are released to every install.",
    ),
)

NAMES: frozenset[str] = frozenset(f.name for f in FLAGS)


def check(names: list[str]) -> None:
    """Refuses a name the registry does not hold, so a misspelt flag stops a service at start instead of reading off."""
    unknown = sorted(set(names) - NAMES)
    if unknown:
        raise ValueError(f"unknown flag {', '.join(unknown)} in OPS_FLAGS; known flags: {', '.join(sorted(NAMES))}")


@dataclass(frozen=True)
class Flags:
    """The install's resolved flags: the names the install config turns on."""

    turned_on: frozenset[str] = frozenset()

    def on(self, name: FlagName) -> bool:
        # A name outside the registry is a typo in code; reading it as off would hide the feature forever.
        if name not in NAMES:
            raise KeyError(f"no flag named {name!r}")
        return name in self.turned_on

    def resolved(self) -> list[dict[str, object]]:
        """Every flag in registry order with whether it is on, for platform-service's answer."""
        return [{"name": f.name, "description": f.description, "on": f.name in self.turned_on} for f in FLAGS]
