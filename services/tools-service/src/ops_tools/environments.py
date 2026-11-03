"""The environments tools-service knows, as one list. A module's versions are promoted through all of them; a
connection holds keys for those marked `keys`. Each route's environment type below is checked against this list
(tests/test_environments.py), so adding a row and forgetting a route, or the reverse, fails a test rather than a call.

Team-defined environments are planned as rows of this list; until then the rows are fixed here."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class EnvironmentRow:
    id: str
    label: str
    # The one environment live runs call.
    production: bool = False
    # Whether a connection holds keys for it. Only a module's versions are promoted through an environment without.
    keys: bool = False

    def view(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "production": self.production, "keys": self.keys}


ROWS: tuple[EnvironmentRow, ...] = (
    EnvironmentRow("dev", "Dev"),
    EnvironmentRow("test", "Test", keys=True),
    EnvironmentRow("production", "Production", production=True, keys=True),
)

# The types routes accept, kept equal to ROWS by tests/test_environments.py.
ModuleEnvironment = Literal["dev", "test", "production"]
ConnectionEnvironment = Literal["test", "production"]

CONNECTION_ENVIRONMENTS: tuple[str, ...] = tuple(r.id for r in ROWS if r.keys)
TEST, PRODUCTION = CONNECTION_ENVIRONMENTS


def views() -> list[dict[str, Any]]:
    """Every environment, in order, as `GET /v1/connection-kinds` serves it."""
    return [r.view() for r in ROWS]


def connection_views() -> list[dict[str, Any]]:
    """The environments a connection holds keys for, in order."""
    return [r.view() for r in ROWS if r.keys]
