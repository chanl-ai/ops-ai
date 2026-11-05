"""The environments tools-service knows, as one list: a module's versions are promoted through all of them. A call
is made in a run of one kind, test or live; live runs call the production environment. An account is not set per
environment: a test run uses the app's test account when it has one (connections.records.account_for). Each route's
environment type below is checked against this list (tests/test_environments.py), so adding a row and forgetting a
route, or the reverse, fails a test rather than a call.

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
    # Whether a call is made in it: a test run or a live one. Only a module's versions are promoted through the rest.
    runs: bool = False

    def view(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label, "production": self.production}


ROWS: tuple[EnvironmentRow, ...] = (
    EnvironmentRow("dev", "Dev"),
    EnvironmentRow("test", "Test", runs=True),
    EnvironmentRow("production", "Production", production=True, runs=True),
)

# The types routes accept, kept equal to ROWS by tests/test_environments.py.
ModuleEnvironment = Literal["dev", "test", "production"]
# The kind of run a call is made in: a test run (the Test panel, a draft, a tool's Real run) or a live one.
RunKind = Literal["test", "live"]

TEST: RunKind = "test"
LIVE: RunKind = "live"
