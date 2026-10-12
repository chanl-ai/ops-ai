"""The check every service's test conftest runs before collection: tests use the test database and nothing else.

A suite that fell back to Settings' default URL migrated the live `ops_runtime` once, under every running stack. The
make test targets create the test database (scripts/test_db.py) and export it as OPS_TEST_DATABASE_URL with
OPS_DATABASE_URL set to the same; any other PostgreSQL database is refused before a test, fixture or migration runs.
SQLite URLs are in-process and always allowed.
"""

from __future__ import annotations

from urllib.parse import urlsplit

LIVE = "ops_runtime"


def _target(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return f"{parts.hostname}:{parts.port}", parts.path.lstrip("/")


def refusal(database_url: str, test_url: str | None) -> str | None:
    """Why tests must not run on `database_url`, or None when it is `test_url`, the OPS_TEST_DATABASE_URL make set."""
    if not database_url.startswith("postgresql"):
        return None
    _, name = _target(database_url)
    fix = "run the suite through `make test` (it sets OPS_TEST_DATABASE_URL), never on the live database"
    if name == LIVE:
        return f"tests refuse database {LIVE}, the live stack's: {fix}"
    if not test_url:
        return f"tests refuse database {name}: OPS_TEST_DATABASE_URL is unset; {fix}"
    if _target(test_url) != _target(database_url):
        return f"tests refuse database {name}: it is not OPS_TEST_DATABASE_URL's ({_target(test_url)[1]}); {fix}"
    return None
