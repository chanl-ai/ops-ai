"""The check every service's test conftest runs before collection: tests use the test database and nothing else.

A suite that fell back to Settings' default URL migrated the live `ops_runtime` once, under every running stack. The
make test targets create the test database (scripts/test_db.py) and export it as OPS_TEST_DATABASE_URL with
OPS_DATABASE_URL set to the same; any other PostgreSQL database is refused before a test, fixture or migration runs.
SQLite URLs are in-process and always allowed.

A parallel run (`make test PAR=n`, pytest-xdist) gives each worker its own copy of the test database, `<name>_gw<k>`,
made by scripts/test_db.py from the migrated one; `use_worker_database` points a worker's process at its copy before
anything reads the URL, since the suites empty tables and seed fixed tenants between tests.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .settings import (
    LIVE_DATABASE,
    STACK_SERVICE_ENV,
    isolate_from_stack,
    migration_test_urls,
    unanswered_endpoints,
    use_worker_database,
    worker_url,
)

__all__ = [
    "LIVE",
    "STACK_SERVICE_ENV",
    "isolate_from_stack",
    "migration_refusal",
    "refusal",
    "unanswered_endpoints",
    "use_worker_database",
    "worker_url",
]

LIVE = LIVE_DATABASE


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


# The name ops_store.conformance.sql_server_database gives a scratch database (`<prefix>_<8 hex>`, dropped afterwards).
_SCRATCH_SQL_SERVER = re.compile(r"ops_\w+_test_[0-9a-f]{8}")


def migration_refusal(database_url: str) -> str | None:
    """Why a migration proof (ops_store.testing.prove_chain), which downgrades, must not run on `database_url`, or None.
    PostgreSQL: only OPS_TEST_DATABASE_URL's database (refusal). SQL Server: only a scratch database. Either way
    OPS_DATABASE_URL must name the same database, since the chain's env.py migrates that one, not the URL passed."""
    if database_url.startswith("mssql"):
        name = _target(database_url)[1]
        if not _SCRATCH_SQL_SERVER.fullmatch(name):
            return f"a migration proof refuses SQL Server database {name}: only a scratch one (sql_server_schema)"
    elif (why := refusal(database_url, migration_test_urls()[0])) is not None:
        return why
    env_url = migration_test_urls()[1]
    if env_url is None or _target(env_url) != _target(database_url):
        return "a migration proof refuses to run: OPS_DATABASE_URL, which the chain's env.py migrates, is not its URL"
    return None
