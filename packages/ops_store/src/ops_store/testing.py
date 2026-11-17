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
import importlib
import io
import math
import re
import sys
from collections.abc import Callable, Collection, Generator, Iterable
from contextlib import contextmanager, redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.testdb import migration_refusal

from . import background
from .conformance import sql_server_database
from .schema import MSSQL_PRECONDITIONS, differences, isolated_tables

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


# Migration chains ------------------------------------------------------------------------------------------------

DEPLOY_DATABASE = GOLDEN.parents[1]


@dataclass(frozen=True)
class ChainFacts:
    """What deploy/database holds about one chain: where its SQL Server revisions begin, which revisions are online
    only, its metadata (every MetaData its store packages define) and the tables no metadata defines yet."""

    baseline: str | None
    online_only: frozenset[str]
    metadata: tuple[sa.MetaData, ...]
    excluded: frozenset[str]


def chain_facts(chain: str) -> ChainFacts:
    """Read from deploy/database's own modules (mssql.BASELINE, schema.ONLINE_ONLY, models.chain_metadata), so a
    service's migration test keeps no copy of them."""
    if str(DEPLOY_DATABASE) not in sys.path:
        sys.path.insert(0, str(DEPLOY_DATABASE))
    mssql, models, schema = (importlib.import_module(m) for m in ("mssql", "models", "schema"))
    return ChainFacts(
        baseline=mssql.BASELINE.get(chain),
        online_only=frozenset(schema.ONLINE_ONLY.get(chain, ())),
        metadata=tuple(models.chain_metadata(chain)),
        excluded=frozenset(models.EXCLUDED.get(chain, ())),
    )


def _shape(c: sa.Connection, tables: Collection[str], version_table: str) -> set[tuple[object, ...]]:
    """What a schema holds, as the database reflects it, one tuple per fact: each of the chain's tables' columns,
    indexes (a unique constraint's among them), keys and isolation, and the chain's version. schema.differences needs
    CHECK and unique-constraint reflection, which SQLAlchemy's SQL Server dialect lacks, so SQL Server compares this."""
    i = sa.inspect(c)
    present = set(i.get_table_names())
    version = (
        c.execute(sa.select(sa.column("version_num", sa.String)).select_from(sa.table(version_table))).scalar()
        if version_table in present
        else None
    )
    out: set[tuple[object, ...]] = {("version", version)}
    for t in sorted(present & set(tables)):
        out |= {(t, x["name"], str(x["type"]), x["nullable"], x.get("default") is not None) for x in i.get_columns(t)}
        out |= {
            (t, "index", x["name"], tuple(x["column_names"]), bool(x["unique"]), str(x.get("dialect_options", {})))
            for x in i.get_indexes(t)
        }
        out |= {
            (
                t,
                "key",
                x["name"],
                tuple(x["constrained_columns"]),
                tuple(x["referred_columns"]),
                x.get("options", {}).get("ondelete"),
            )
            for x in i.get_foreign_keys(t)
        }
    out |= {("policy", t, kind) for t, kind in isolated_tables(c).items() if t in tables}
    return out | _policy_rules(c, tables)


def _policy_rules(c: sa.Connection, tables: Collection[str]) -> set[tuple[object, ...]]:
    """Each isolation policy's own rule, beside its kind, so a downgrade and re-upgrade that brings a policy back
    weaker (another predicate, column or function body) changes the shape. PostgreSQL: each policy's command, roles,
    USING and WITH CHECK as the server deparses them. SQL Server: each security predicate's type, operation and
    definition (the function and column), and the body of every function a predicate names, spaces collapsed."""
    if c.dialect.name == "postgresql":
        rows = c.execute(
            sa.text(
                "SELECT tablename, policyname, permissive, cmd, roles::text, qual, with_check FROM pg_policies"
                " WHERE schemaname = current_schema()"
            )
        )
        return {("rule", *r) for r in rows if r[0] in tables}
    if c.dialect.name == "mssql":
        rows = c.execute(
            sa.text(
                "SELECT o.name, p.name, sp.predicate_type_desc, sp.operation_desc, sp.predicate_definition"
                " FROM sys.security_predicates sp JOIN sys.security_policies p ON p.object_id = sp.object_id"
                " JOIN sys.objects o ON o.object_id = sp.target_object_id"
                " WHERE p.is_enabled = 1 AND SCHEMA_NAME(o.schema_id) = SCHEMA_NAME()"
            )
        ).all()
        out: set[tuple[object, ...]] = {("rule", *r) for r in rows if r[0] in tables}
        named = " ".join(str(r[4]) for r in rows if r[0] in tables)
        functions = c.execute(
            sa.text(
                "SELECT SCHEMA_NAME(o.schema_id), o.name, OBJECT_DEFINITION(o.object_id) FROM sys.objects o"
                " WHERE o.type IN ('IF', 'FN', 'TF')"
            )
        )
        # Predicate functions live in their own schema (ops_security), named in a definition as [schema].[name].
        # SQL Server keeps a function's text as sent: the golden DDL's ends in `;`, a migration's does not.
        out |= {
            ("function", f"{sch}.{n}", " ".join(str(d).split()).removesuffix(";"))
            for sch, n, d in functions
            if f"[{sch}].[{n}]" in named
        }
        assert not named or any(f[0] == "function" for f in out), "a security predicate names no function read here"
        return out
    return set()


def _on[T](url: str, check: Callable[[sa.Connection], T]) -> T:
    async def go() -> T:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as c:
                return await c.run_sync(check)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _renders_offline(config: Config, start: str, rev: str) -> bool:
    try:
        with redirect_stdout(io.StringIO()):
            command.upgrade(config, f"{start}:{rev}", sql=True)
        return True
    except Exception:  # any failure to render is the finding
        return False


class RefusedDatabase(RuntimeError):
    """prove_chain was pointed at a database that is not a throwaway test database."""


def prove_chain(
    config: Config,
    chain: str,
    url: str,
    *,
    version_table: str | None = None,
    floor: str = "base",
    fresh: str | None = None,
    known: Collection[str] = (),
) -> None:
    """A service's migration chain, run online on the database at `url` (which `config`'s env.py must already read):
    up to head, down to its floor (`base` on PostgreSQL; on SQL Server its baseline, before which revisions are
    PostgreSQL history), up to head, a second upgrade that changes nothing, down one and up again. Then the schema is
    what the chain claims:
    on SQL Server what `fresh` (a scratch database the golden DDL installed) holds, policies included; on PostgreSQL
    the metadata, less the `known` differences (deploy/database/tests/test_model_parity.py LAGGING). Each online-only
    revision the run crossed is refused as offline SQL, as schema.ONLINE_ONLY documents. Synchronous: Alembic's
    environment runs its own event loop. Raises AssertionError on the first failure, and RefusedDatabase before any
    statement when `url` is not a throwaway test database (ops_service_kit.testdb.migration_refusal): the downgrade
    drops tables and data."""
    if (why := migration_refusal(url)) is not None:
        raise RefusedDatabase(why)
    facts = chain_facts(chain)
    table = version_table or f"alembic_version_{chain}"
    tables = {t for md in facts.metadata for t in md.tables} - facts.excluded
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    assert head is not None, f"{chain}: the chain has no single head"
    on_sql_server = url.startswith("mssql")
    if on_sql_server and fresh is None:
        raise ValueError("on SQL Server the head is compared with a fresh golden install: pass `fresh`")
    floor = (facts.baseline or "base") if on_sql_server else floor

    def shape() -> set[tuple[object, ...]]:
        return _on(url, lambda c: _shape(c, tables, table))

    # From head, so the downgrade runs every revision above the floor whatever state the database started in.
    command.upgrade(config, "head")
    command.downgrade(config, floor)
    at_floor = shape()
    assert ("version", None if floor == "base" else floor) in at_floor, f"{chain}: not at {floor} after the downgrade"
    if floor == "base":
        left = {f[0] for f in at_floor if f[0] in tables}
        assert not left, f"{chain}: tables left at base: {sorted(left, key=str)}"
    command.upgrade(config, "head")
    at_head = shape()
    assert ("version", head) in at_head, f"{chain}: not at {head} after the upgrade"
    command.upgrade(config, "head")
    assert shape() == at_head, f"{chain}: a second upgrade changed the schema"
    previous = script.get_revision(head).down_revision
    command.downgrade(config, "-1")
    assert ("version", previous) in shape(), f"{chain}: not at {previous} after down one"
    command.upgrade(config, "head")
    moved = shape()
    changed = (sorted(moved - at_head, key=str), sorted(at_head - moved, key=str))
    assert changed == ([], []), f"{chain}: down one and up again changed the schema: {changed}"

    if on_sql_server:
        assert fresh is not None
        installed = _on(fresh, lambda c: _shape(c, tables, table))
        assert ("version", head) in installed, f"{chain}: the golden DDL is not at {head}; run make db-ddl-golden"
        extra, missing = sorted(moved - installed, key=str), sorted(installed - moved, key=str)
        assert (extra, missing) == ([], []), (
            f"{chain}: migrated but not in the golden DDL {extra}; the reverse {missing}"
        )
    else:
        found = set(_on(url, lambda c: differences(c, facts.metadata, facts.excluded)))
        assert found == set(known), f"{chain}: migrated schema and metadata differ: {sorted(found ^ set(known))}"

    crossed = {r.revision for r in script.iterate_revisions(head, floor)}
    for rev in sorted(facts.online_only & crossed):
        down = script.get_revision(rev).down_revision
        assert isinstance(down, str), f"{chain} {rev}: an online-only merge revision"
        assert not _renders_offline(config, down, rev), f"{chain} {rev}: online only, yet it renders as offline SQL"


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
