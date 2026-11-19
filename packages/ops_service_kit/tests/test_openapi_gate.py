"""The contract gate's refusal of a route the committed document does not hold, and where it runs. The commit hook
skips service builds, so this check is what blocks the merge: `make verify` of a service runs `openapi-check`, which
CI's service job runs for every service the change touches."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI

from ops_service_kit import openapi

ROOT = Path(__file__).resolve().parents[3]


def test_a_route_added_without_regenerating_the_document_is_refused(tmp_path: Path) -> None:
    app = FastAPI(title="probe")
    committed = tmp_path / "openapi.json"
    committed.write_text(openapi.render(app.openapi()))
    allow = tmp_path / "openapi-untyped.txt"
    allow.write_text("# 0 untyped operations\n")

    @app.get("/probe")
    async def probe() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {}

    app.openapi_schema = None
    code, lines = openapi.report(
        app.openapi(), allowlist_path=allow, document_path=committed, committed=None, write=False
    )
    assert code == 1 and any("differs from the app's document" in line for line in lines), lines
    _, after = openapi.report(app.openapi(), allowlist_path=allow, document_path=committed, committed=None, write=True)
    assert not any("differs from the app's document" in line for line in after), after


def prerequisites(makefile: str, target: str, seen: frozenset[str] = frozenset()) -> set[str]:
    """The targets `target` runs, through the targets it names (verify -> checks -> openapi-check)."""
    found = re.search(rf"^{target}:([^#\n]*)", makefile, re.MULTILINE)
    names: set[str] = set(found.group(1).split()) if found else set()
    for name in sorted(names - seen):
        names |= prerequisites(makefile, name, seen | names)
    return names


def test_every_service_with_a_committed_document_runs_the_gate_in_its_verify() -> None:
    """A service with no committed document yet (runner-service) has nothing for the gate to compare."""
    gated = sorted(p.parent for p in ROOT.glob("services/*/openapi.json"))
    assert gated, "no service has a committed document"
    for service in gated:
        assert "openapi-check" in prerequisites((service / "Makefile").read_text(), "verify"), service.name
