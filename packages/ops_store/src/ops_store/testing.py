"""Test helpers for a service's own suite. `loop_reports_failure` is the one test every background process has
(tests/test_loop_health.py): that a pass which raises shows on the service's `/health/background`.

  async def test_the_relay_reports_a_failed_pass(client, agents):
      await loop_reports_failure(client, "files_relay", lambda: agents.go_down())

`sql_server_schema` puts a service's store tests on SQL Server beside PostgreSQL: its `database_url` fixture is
parametrised over DATABASES, and the SQL Server case is a scratch database holding the chain's golden DDL. The package
does not depend on pytest, so the service's conftest makes the fixture:

  @pytest.fixture(scope="session", params=DATABASES)
  def database_url(request):
      if request.param == "postgresql": ...migrate the test database and return its URL...
      with sql_server_schema("files", os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")) as url:
          if url is None:
              pytest.skip(NO_SQL_SERVER)
          yield url

A test that needs a PostgreSQL feature carries `@pytest.mark.postgresql_only("<why>")`; the conftest's
`pytest_collection_modifyitems` drops its SQL Server case with `postgresql_only`, which names each one dropped.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol, cast

from . import background
from .conformance import sql_server_database
from .schema import MSSQL_PRECONDITIONS

# The databases a store test runs on; the SQL Server case skips unless OPS_MSSQL_SERVER and MSSQL_SA_PASSWORD are set.
DATABASES = ("postgresql", "mssql")
NO_SQL_SERVER = "set OPS_MSSQL_SERVER and MSSQL_SA_PASSWORD to run on SQL Server"
# The reviewed SQL Server DDL per chain (deploy/database/golden/mssql), in the checkout the tests run from.
GOLDEN = Path(__file__).resolve().parents[4] / "deploy" / "database" / "golden" / "mssql"
_GO = re.compile(r"^GO$", re.M)
_CHAIN_HEADER = re.compile(r"^-- (\w+)-service$", re.M)
_USER_FOR_LOGIN = re.compile(r"CREATE USER (\w+) FOR LOGIN \1")

# How often the report is read while waiting for the failure to show.
POLL_S = 0.05
# The longest wait for a process whose listed interval is longer; its test runs the loop on a short interval.
WAIT_MAX_S = 10.0


class Reply(Protocol):
    def json(self) -> Any: ...


class HealthClient(Protocol):
    """The part of an HTTP test client the check uses; `httpx.AsyncClient` on the service's app is one."""

    async def get(self, url: str, /) -> Reply: ...


async def _row(client: HealthClient, key: str) -> dict[str, Any]:
    answer: Any = (await client.get("/health/background")).json()
    body = cast(dict[str, Any], answer)
    # A service answers the bare report; one behind the response envelope carries it under `data`.
    listed = cast(list[dict[str, Any]], (body.get("data") or body).get("processes") or [])
    row = next((p for p in listed if p.get("key") == key), None)
    assert row is not None, f"/health/background does not list {key}; it shows {[p.get('key') for p in listed]}"
    return row


async def loop_reports_failure(
    client: HealthClient, key: str, trip: Callable[[], None], *, within_s: float | None = None
) -> None:
    """Makes one pass raise, waits one interval, asserts /health/background shows the key with last_error set.

    `trip` arranges for the process's next pass to raise (a dependency taken down, a store method that throws). The
    loop must already be running on the app `client` calls. The wait is the process's listed interval plus its first
    retry, at most WAIT_MAX_S, or `within_s`. The error has to be newer than any the report showed before `trip`,
    so an old failure, or a loop that never reaches its heartbeat, fails. The state is not asserted: a pass that
    fails once has recovered, and reads as running again, by the time the report is read."""
    process = background.BY_KEY.get(key)
    assert process is not None, f"{key} is not on ops_store.background.PROCESSES"
    before = (await _row(client, key)).get("lastErrorAt") or 0.0
    trip()
    wait = within_s if within_s is not None else min(WAIT_MAX_S, (process.every_s or 0.0) + background.BACKOFF_START_S)
    row: dict[str, Any] = {}
    for _ in range(math.ceil(wait / POLL_S) + 1):
        row = await _row(client, key)
        if row.get("lastError") and (row.get("lastErrorAt") or 0.0) > before:
            return
        await asyncio.sleep(POLL_S)
    raise AssertionError(
        f"{key} did not report a failed pass on /health/background within {wait:g} s of the trip; its row: {row}"
    )


# Both databases --------------------------------------------------------------------------------------------------


def _batches(script: str) -> list[str]:
    """A sqlcmd script's batches (split on GO lines), leaving out any that holds only comments."""
    out: list[str] = []
    for batch in _GO.split(script):
        if any(line.strip() and not line.lstrip().startswith("--") for line in batch.splitlines()):
            out.append(batch.strip("\n"))
    return out


def golden_bundle(chain: str, golden: Path = GOLDEN) -> list[str]:
    """The batches that install `chain` on an empty SQL Server database: the bundle's preconditions, the chain's golden
    file (stamped at its head), then its part of grants.sql. Logins are server-wide and roles.sql changes their
    passwords, so a test makes none: the runtime user is made without one, which the grants and the system user's
    IMPERSONATE need, and the tests connect as the administrator, to whom the security policies apply as well."""
    found = sorted(golden.glob(f"[0-9][0-9]-{chain}.sql"))
    if len(found) != 1:
        raise FileNotFoundError(f"no golden SQL Server file for {chain} in {golden}; run make db-ddl-golden")
    grants: list[str] = []
    owner = None
    for batch in _batches((golden / "grants.sql").read_text()):
        if header := _CHAIN_HEADER.search(batch):
            owner = header.group(1)
        if owner == chain:
            grants.append(_USER_FOR_LOGIN.sub(r"CREATE USER \1 WITHOUT LOGIN", batch))
    return [*MSSQL_PRECONDITIONS, *_batches(found[0].read_text()), *grants]


@contextmanager
def sql_server_schema(
    chain: str, server: str | None, password: str | None, golden: Path = GOLDEN
) -> Generator[str | None]:
    """The async URL of a scratch SQL Server database holding `chain`'s golden schema, dropped afterwards (the
    database only); None when `server` (OPS_MSSQL_SERVER, host,port) or `password` (MSSQL_SA_PASSWORD) is unset."""
    batches = golden_bundle(chain, golden) if server and password else None
    with sql_server_database(f"ops_{chain}_test", server, password, batches=batches) as url:
        yield url


class _Item(Protocol):
    @property
    def nodeid(self) -> str: ...

    def get_closest_marker(self, name: str, /) -> Any: ...


def postgresql_only[T: _Item](items: Iterable[T]) -> tuple[list[T], list[tuple[str, str]]]:
    """`items` without the SQL Server case of each test marked `postgresql_only("<why>")`, and (node id, why) for
    each one dropped. A marker without a reason is refused, so every dropped case says why."""
    keep: list[T] = []
    dropped: list[tuple[str, str]] = []
    for item in items:
        marker = item.get_closest_marker("postgresql_only")
        # A parametrised test's callspec names the case; a test without database_url has none for it.
        callspec = getattr(item, "callspec", None)
        on = callspec.params.get("database_url") if callspec is not None else None
        if marker is None or on != "mssql":
            keep.append(item)
            continue
        why = marker.args[0] if marker.args else ""
        if not why:
            raise ValueError(f"{item.nodeid}: postgresql_only needs the reason the test cannot run on SQL Server")
        dropped.append((item.nodeid, str(why)))
    return keep, dropped
