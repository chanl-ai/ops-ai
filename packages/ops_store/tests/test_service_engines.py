"""Every service opens its database through open_database, so each one tests a pooled connection before using it. A
store that calls create_async_engine itself loses that check and fails its first request after the database closed
an idle connection (c-384). Migrations, scripts and experiments run once and exit, so they are not checked."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_no_service_source_builds_its_own_engine() -> None:
    found = [
        f"{p.relative_to(ROOT)}:{n}"
        for p in sorted(ROOT.glob("services/*/src/**/*.py"))
        for n, line in enumerate(p.read_text().splitlines(), 1)
        if "create_async_engine(" in line
    ]
    assert found == []
