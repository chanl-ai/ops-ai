"""The SQL Server and Azure SQL dialect of the schema tool (c-344; ADR docs/architecture/decisions/database-support.md).

    make db-ddl DIALECT=mssql OUT=<dir>                  roles.sql, one file per chain, bundle.sql, grants.sql, manifest
    make db-upgrade-sql DIALECT=mssql FROM=<ref> TO=<ref>  upgrade.sql and downgrade.sql from Alembic's offline SQL
    make db-ddl-golden                                    deploy/database/golden/mssql/ from this checkout's models

No server is needed. The baseline is compiled from each chain's store metadata (models.chain_metadata) with SQLAlchemy's
mssql dialect, because 53 of the 150 PostgreSQL migrations hold SQL that cannot run on SQL Server; c-342 holds the
metadata equal to what the migrations build. Each chain's baseline is stamped at its head, and only revisions after
BASELINE render for SQL Server. Tenant isolation is a security policy per TENANT_SCOPED table, the SQL Server form of
the forced row-level security those tables carry on PostgreSQL. Every file is a sqlcmd script (`sqlcmd -b -i`): GO
ends each batch, since CREATE FUNCTION must open one.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import mssql
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.schema import CreateColumn, CreateIndex, CreateTable
from sqlalchemy.sql.compiler import DDLCompiler
from sqlalchemy.sql.ddl import sort_tables
from sqlalchemy.sql.schema import ColumnCollectionConstraint

sys.path.insert(0, str(Path(__file__).resolve().parent))
from models import chain_metadata
from schema import MIGRATOR, ONLINE_ONLY, Checkout, chains, exported, runtime_role, sha256, write_sums

from ops_store.schema import tenant_scoped

GOLDEN = Path(__file__).resolve().parent / "golden" / "mssql"
OFFLINE_URL = "mssql+aioodbc://offline:offline@localhost:1/offline"
COLLATION = "Latin1_General_100_BIN2_UTF8"
SECURITY = "ops_security"
# PostgreSQL's ops_runtime_system, the BYPASSRLS role agents-service's loops switch to before they know a thread's
# tenant, as a database user without a login: ops_agents_runtime alone may impersonate it (EXECUTE AS USER in
# ops_store.dialect.system_tx), and the agents read predicate passes every tenant for it. A row predicate cannot limit
# columns, so what it reads is held by grants, table by table and column by column as on PostgreSQL: the agents
# migrations' grants (0021, 0024, 0045, 0049, 0072), restated here and held equal by test_model_parity.py.
SYSTEM_USER = "ops_runtime_system"
SYSTEM_CHAIN = "agents"
SYSTEM_READS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "graph_threads": (("SELECT",), ()),
    "graph_runs": (("SELECT",), ()),
    "thread_events": (("SELECT",), ()),
    "review_decisions": (("SELECT",), ()),
    "review_approvals": (("SELECT",), ()),
    "engine_definitions": (("SELECT",), ()),
    "engine_work": (("SELECT", "UPDATE"), ()),
    # The retention sweep lists the tenants holding memories; it never reads what an agent remembers.
    "agent_memories": (("SELECT",), ("tenant_id",)),
}
# Each chain's first SQL Server baseline (2026-10-19, each chain's head that day). Revisions up to and including it are
# PostgreSQL history and never render for SQL Server; every later one is written with Alembic operations both run.
BASELINE = {
    "agents": "0070_engine_definitions_archived",
    "tools": "tools_0030_call_channel",
    "models": "models_0006",
    "kb": "kb_0009",
    "platform": "0025_connections_cells",
    "files": "files_0009",
    "documents": "documents_0009",
}
# Offline SQL holding one of these was written for PostgreSQL (op.execute text passes through unchanged).
POSTGRES_ONLY = re.compile(
    r"DO \$\$|CREATE POLICY|ROW LEVEL SECURITY|current_setting|::\w|jsonb|SET LOCAL|\bRAISE\b", re.I
)
_OMIT = "mssql_omit"


class Refused(SystemExit):
    """A schema object SQL Server cannot get from the models as they are, named so its owner can fix the model."""


# --- compiling a chain ----------------------------------------------------------------------------------------------


@compiles(CreateColumn, "mssql")
def _column(element: CreateColumn[Any], compiler: DDLCompiler, **kw: Any) -> str | None:
    # Returning None leaves the column out of CREATE TABLE (SQLAlchemy's documented hook).
    if element.element.info.get(_OMIT):
        return None
    return compiler.visit_create_column(element, **kw)  # pyright: ignore[reportUnknownMemberType]


def dialect() -> sa.Dialect:
    """SQL Server 2025, the oldest supported. With no server to ask, the compiler otherwise assumes one older than
    2008 and renders Date as DATETIME; deprecate_large_types makes Text VARCHAR(max) and binary VARBINARY(max), not
    TEXT and IMAGE."""
    d = mssql.dialect(deprecate_large_types=True)
    d.server_version_info = (17, 0)
    return d


def _postgres_only(column: sa.Column[Any]) -> bool:
    return type(column.type).__module__.startswith("sqlalchemy.dialects.postgresql")


def _key_name(table: str, columns: Iterable[str], suffix: str) -> str:
    """PostgreSQL's name for an unnamed constraint, so a later migration names the same object on both databases."""
    return f"{table}_{'_'.join(columns)}_{suffix}"[:128]


def _not_null(columns: Iterable[sa.Column[Any]]) -> list[sa.ColumnElement[bool]]:
    return [c.is_not(None) for c in columns if c.nullable]


def _identity(con: sa.Constraint) -> tuple[str, str, tuple[str, ...], str]:
    columns = tuple(c.name for c in con.columns) if isinstance(con, ColumnCollectionConstraint) else ()
    target = ",".join(e.target_fullname for e in con.elements) if isinstance(con, sa.ForeignKeyConstraint) else ""
    body = str(con.sqltext) if isinstance(con, sa.CheckConstraint) else ""
    return (type(con).__name__, str(con.name or ""), columns, target + body)


@dataclass
class Chain:
    name: str
    tables: list[sa.Table]
    omitted: list[str] = field(default_factory=lambda: [])


def chain_tables(chain: str, metadatas: Iterable[sa.MetaData]) -> Chain:
    """The chain's tables copied onto a scratch MetaData and shaped for SQL Server; the models are left untouched."""
    scratch = sa.MetaData()
    copies: list[sa.Table] = []
    for m in metadatas:
        for t in m.tables.values():
            copy = t.to_metadata(scratch)
            # to_metadata copies constraints from a set, so their creation order (which CreateTable renders them in)
            # would change from run to run; the originals' order keeps the DDL byte-for-byte stable.
            order = {_identity(c): c._creation_order for c in t.constraints}  # pyright: ignore[reportPrivateUsage]
            for c in copy.constraints:
                c._creation_order = order[_identity(c)]  # pyright: ignore[reportPrivateUsage]
            copies.append(copy)
    found = Chain(chain, list(sort_tables(copies)))
    refused: list[str] = []
    for t in found.tables:
        dropped = {c.name for c in t.columns if _postgres_only(c)}
        for name in sorted(dropped):
            t.c[name].info[_OMIT] = True
            found.omitted.append(f"{t.name}.{name} ({t.c[name].type.__class__.__name__})")
        for ix in list(t.indexes):
            if {c.name for c in ix.columns} & dropped:
                t.indexes.discard(ix)
                found.omitted.append(f"index {ix.name}")
                continue
            if (
                ix.dialect_options["postgresql"].get("where") is not None
                and ix.dialect_options["mssql"]["where"] is None
            ):
                refused.append(f"{chain} {t.name}.{ix.name}: postgresql_where without its mssql_where twin")
                continue
            if ix.unique:
                # SQL Server lets one NULL into a unique index, PostgreSQL any number: filtering out rows where a key
                # column is NULL enforces exactly the rows PostgreSQL enforces.
                where = [*_not_null(ix.columns)]
                if where:
                    twin = ix.dialect_options["mssql"]["where"]
                    ix.dialect_options["mssql"]["where"] = sa.and_(*([twin] if twin is not None else []), *where)
        for con in list(t.constraints):
            columns = [c.name for c in con.columns] if isinstance(con, ColumnCollectionConstraint) else []
            if isinstance(con, sa.PrimaryKeyConstraint) and con.name is None:
                con.name = f"{t.name}_pkey"
            elif isinstance(con, sa.UniqueConstraint):
                name = con.name if isinstance(con.name, str) else _key_name(t.name, columns, "key")
                if _not_null(con.columns):
                    # A UNIQUE constraint cannot be filtered; the filtered unique index is its SQL Server form.
                    t.constraints.discard(con)
                    sa.Index(name, *con.columns, unique=True, mssql_where=sa.and_(*_not_null(con.columns)))
                elif con.name is None:
                    con.name = name
            elif isinstance(con, sa.ForeignKeyConstraint) and con.name is None:
                con.name = _key_name(t.name, columns, "fkey")
            elif isinstance(con, sa.CheckConstraint) and con.name is None:
                refused.append(f"{chain} {t.name}: a CHECK constraint without a name")
    if refused:
        raise Refused("SQL Server DDL cannot be compiled from these models:\n  " + "\n  ".join(refused))
    return found


def _sql(element: Any) -> str:
    return str(element.compile(dialect=dialect())).strip()


def tenant_column(table: sa.Table) -> sa.Column[Any]:
    """The column a TENANT_SCOPED table is isolated by: tenant_id, or a tenant table's own single-column key."""
    if "tenant_id" in table.c:
        return table.c.tenant_id
    key = list(table.primary_key.columns)
    if table.name == "tenants" and len(key) == 1:
        return key[0]
    raise Refused(f"{table.name} is TENANT_SCOPED but has no tenant_id column")


def security(chain: str, tables: list[sa.Table]) -> list[str]:
    """Two schema-bound predicate functions for the chain, and one security policy per TENANT_SCOPED table.

    Reads see the tenant the transaction acts for (`ops_store.dialect.tenant_tx` sets SESSION_CONTEXT tenant_id); in
    the agents chain they also pass every tenant for SYSTEM_USER, whose grants limit what it reads. Writes must be the
    transaction's tenant. Nothing a login can set for itself opens other tenants' rows. A NULL or missing tenant
    matches no row, so a connection used with no tenant sees nothing."""
    marked = [t for t in tables if tenant_scoped(t)]
    if not marked:
        return []
    kinds = {tenant_column(t).type.compile(dialect=dialect()) for t in marked}
    if len(kinds) != 1:
        raise Refused(f"{chain}: tenant columns of different types {sorted(kinds)}; one predicate cannot take them")
    (kind,) = kinds
    tenant = f"CAST(SESSION_CONTEXT(N'tenant_id') AS {kind})"
    read, write = f"{SECURITY}.{chain}_tenant_read", f"{SECURITY}.{chain}_tenant_write"
    out = [
        f"IF SCHEMA_ID(N'{SECURITY}') IS NULL EXEC (N'CREATE SCHEMA {SECURITY} AUTHORIZATION dbo');",
        f"CREATE FUNCTION {read} (@tenant_id {kind})\nRETURNS TABLE WITH SCHEMABINDING AS RETURN\n"
        f"SELECT 1 AS visible WHERE @tenant_id = {tenant}"
        + (f" OR USER_NAME() = N'{SYSTEM_USER}';" if chain == SYSTEM_CHAIN else ";"),
        f"CREATE FUNCTION {write} (@tenant_id {kind})\nRETURNS TABLE WITH SCHEMABINDING AS RETURN\n"
        f"SELECT 1 AS allowed WHERE @tenant_id = {tenant};",
    ]
    for t in marked:
        col = tenant_column(t).name
        out.append(
            f"CREATE SECURITY POLICY {SECURITY}.{t.name}_tenant\n"
            f"    ADD FILTER PREDICATE {read}({col}) ON dbo.{t.name},\n"
            f"    ADD BLOCK PREDICATE {write}({col}) ON dbo.{t.name} AFTER INSERT,\n"
            f"    ADD BLOCK PREDICATE {write}({col}) ON dbo.{t.name} AFTER UPDATE\n"
            "    WITH (STATE = ON, SCHEMABINDING = ON);"
        )
    return out


# --- version tables -------------------------------------------------------------------------------------------------

_STAMP_NOISE = re.compile(r"^(BEGIN TRANSACTION;|COMMIT;|GO|-- Running stamp_revision.*)\s*$", re.M)


def alembic_sql(checkout: Checkout, chain: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(checkout.root / ".venv" / "bin" / "alembic"), *args, "--sql"],
        cwd=checkout.root / "services" / f"{chain}-service",
        env=checkout.env(OFFLINE_URL),
        capture_output=True,
        text=True,
        check=False,
    )


def stamp(checkout: Checkout, chain: str, head: str) -> tuple[str, list[str]]:
    """The chain's version table and its row at `head`, as Alembic writes them for SQL Server."""
    run = alembic_sql(checkout, chain, "stamp", head)
    if run.returncode:
        raise SystemExit(f"{chain}-service: alembic stamp {head} --sql failed: {run.stderr[-1500:]}")
    body = _STAMP_NOISE.sub("", run.stdout).replace(" OUTPUT inserted.version_num", "")
    statements = [s.strip() + ";" for s in body.split(";") if s.strip()]
    table = re.search(r"CREATE TABLE (\w+)", body)
    if table is None:
        raise SystemExit(f"{chain}-service: alembic stamp wrote no version table")
    return table.group(1), statements


# --- the files ------------------------------------------------------------------------------------------------------

HEAD = "-- Ops AI schema for SQL Server, compiled from the store models by deploy/database/mssql.py; do not edit.\n"


def batches(statements: Iterable[str]) -> str:
    return "".join(f"{s}\nGO\n" for s in statements)


PRECONDITIONS = batches(
    [
        "SET XACT_ABORT ON;",
        "IF CONVERT(nvarchar(128), DATABASEPROPERTYEX(DB_NAME(), 'Collation')) <> N'" + COLLATION + "'\n"
        f"    THROW 50001, N'Ops AI needs the database collation {COLLATION}', 1;\n"
        "IF NOT EXISTS (SELECT 1 FROM sys.databases WHERE name = DB_NAME() AND is_read_committed_snapshot_on = 1)\n"
        "    THROW 50002, N'Ops AI needs READ_COMMITTED_SNAPSHOT ON', 1;\n"
        "IF (SELECT compatibility_level FROM sys.databases WHERE name = DB_NAME()) < 160\n"
        "    THROW 50003, N'Ops AI needs compatibility level 160 or higher', 1;",
    ]
)


@dataclass
class Compiled:
    files: dict[str, str]
    chains: list[dict[str, Any]]


def compile_all(
    checkout: Checkout, metadata_of: Callable[[str], Iterable[sa.MetaData]], only: Iterable[str] | None = None
) -> Compiled:
    """Every file of the baseline but manifest.json and SHA256SUMS, from the chains' metadata; no ref in the text, so
    the golden files change only when the models (or a head) do."""
    order = [c for c in (only or chains()) if checkout.has(c)]
    files: dict[str, str] = {}
    summary: list[dict[str, Any]] = []
    bodies: list[str] = []
    for chain in order:
        i = chains().index(chain) + 1
        head = checkout.head(chain) or ""
        if before_baseline(checkout, chain, head or None):
            pin = BASELINE[chain]
            raise Refused(f"{checkout.ref}: {chain} is at {head or 'base'}, before its SQL Server baseline {pin}")
        c = chain_tables(chain, metadata_of(chain))
        version_table, stamped = stamp(checkout, chain, head)
        statements: list[str] = []
        for t in c.tables:
            statements.append(_sql(CreateTable(t)) + ";")
            statements += [_sql(CreateIndex(ix)) + ";" for ix in sorted(t.indexes, key=lambda x: str(x.name))]
        statements += security(chain, c.tables)
        statements += stamped
        omitted = "".join(f"-- not on SQL Server yet: {o}\n" for o in c.omitted)
        body = f"-- {chain}-service, stamped at {head}\n" + omitted + batches(statements)
        files[f"{i:02d}-{chain}.sql"] = HEAD + "-- For review; apply bundle.sql, not these.\n" + body
        bodies.append(body)
        summary.append(
            {
                "name": chain,
                "head": head,
                "baseline": BASELINE.get(chain),
                "versionTable": version_table,
                "runtimeRole": runtime_role(chain),
                "tables": [t.name for t in c.tables],
                "omitted": c.omitted,
            }
        )
    files["roles.sql"] = HEAD + roles_script(order)
    files["bundle.sql"] = (
        HEAD + f"-- Run as {MIGRATOR} (the database owner) with sqlcmd -b, on an empty database made by roles.sql;\n"
        "-- then grants.sql.\n" + PRECONDITIONS + "".join(bodies)
    )
    files["grants.sql"] = HEAD + grants_script(summary)
    return Compiled(files, summary)


def roles_script(order: list[str]) -> str:
    logins = [MIGRATOR, *(runtime_role(c) for c in order)]
    out = [
        "-- Run once per server in master by a server administrator, with each password as a sqlcmd variable:\n",
        "--   sqlcmd -b -d master -i roles.sql -v database=ops " + " ".join(f"{n}_password=..." for n in logins) + "\n",
        "-- Runs again safely: an existing login gets the password given, an existing database is left as it is.\n",
        f"-- The database: collation {COLLATION} (VARCHAR holds UTF-8, comparisons are binary like PostgreSQL), and\n",
        "-- READ_COMMITTED_SNAPSHOT on so readers never block writers. bundle.sql refuses a database without both.\n",
        "-- Each runtime login's database user, with DML on its own tables only, is made by grants.sql.\n\n",
    ]
    statements = [
        f"IF SUSER_ID(N'{n}') IS NULL CREATE LOGIN {n} WITH PASSWORD = N'$({n}_password)', CHECK_POLICY = ON;\n"
        f"ELSE ALTER LOGIN {n} WITH PASSWORD = N'$({n}_password)';"
        for n in logins
    ]
    statements += [
        f"IF DB_ID(N'$(database)') IS NULL CREATE DATABASE [$(database)] COLLATE {COLLATION};",
        "ALTER DATABASE [$(database)] SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE;",
        f"-- The migrator owns the database (it is dbo there) and applies the bundle and every upgrade; it is not a\n"
        f"-- server administrator. Security policies apply to it too.\n"
        f"ALTER AUTHORIZATION ON DATABASE::[$(database)] TO {MIGRATOR};",
    ]
    return "".join(out) + batches(statements)


def grants_script(chains_: list[dict[str, Any]]) -> str:
    out = [
        f"-- Run as {MIGRATOR} in the database after the bundle and after each upgrade; every statement runs again.\n",
        "-- Each service's user: SELECT, INSERT, UPDATE, DELETE on its own tables and SELECT on its version table.\n",
        "-- No other permission, so it can create, alter or drop nothing, read no other service's tables, and\n",
        f"-- every security policy applies to it. The agents user may also impersonate {SYSTEM_USER} (no login),\n",
        "-- which reads every tenant's rows of the tables and columns granted to it below, as on PostgreSQL.\n",
    ]
    statements: list[str] = []
    for c in chains_:
        user = c["runtimeRole"]
        statements.append(
            f"-- {c['name']}-service\n"
            f"IF USER_ID(N'{user}') IS NULL CREATE USER {user} FOR LOGIN {user} WITH DEFAULT_SCHEMA = dbo;"
        )
        statements.append(
            "\n".join(f"GRANT SELECT, INSERT, UPDATE, DELETE ON dbo.{t} TO {user};" for t in c["tables"])
            + f"\nGRANT SELECT ON dbo.{c['versionTable']} TO {user};"
        )
        if c["name"] == SYSTEM_CHAIN:
            statements.append(f"IF USER_ID(N'{SYSTEM_USER}') IS NULL CREATE USER {SYSTEM_USER} WITHOUT LOGIN;")
            statements.append(
                "\n".join(
                    f"GRANT {', '.join(privileges)} ON dbo.{t}"
                    + (f" ({', '.join(columns)})" if columns else "")
                    + f" TO {SYSTEM_USER};"
                    for t, (privileges, columns) in SYSTEM_READS.items()
                )
                + f"\nGRANT IMPERSONATE ON USER::{SYSTEM_USER} TO {user};"
            )
    return "".join(out) + batches(statements)


def write_ddl(checkout: Checkout, out: Path) -> dict[str, Any]:
    compiled = compile_all(checkout, chain_metadata)
    stamp_line = f"-- At {checkout.ref} ({checkout.commit[:12]}).\n"
    out.mkdir(parents=True, exist_ok=True)
    files = {n: t.replace(HEAD, HEAD + stamp_line, 1) for n, t in compiled.files.items()}
    for name, text in files.items():
        (out / name).write_text(text)
    manifest = {
        "ref": checkout.ref,
        "commit": checkout.commit,
        "dialect": "mssql",
        "collation": COLLATION,
        "migrator": MIGRATOR,
        "chains": compiled.chains,
        "files": {n: sha256(t) for n, t in sorted(files.items())},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    write_sums(out)
    return manifest


def write_golden(checkout: Checkout, out: Path = GOLDEN) -> list[str]:
    """One golden file per chain that compiles, plus roles.sql and grants.sql; returns the refusals of the rest."""
    refused: list[str] = []
    ok: list[str] = []
    for chain in chains():
        try:
            chain_tables(chain, chain_metadata(chain))
            ok.append(chain)
        except Refused as e:
            refused.append(str(e))
    compiled = compile_all(checkout, chain_metadata, ok)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.sql"):
        old.unlink()
    for name, text in compiled.files.items():
        if name != "bundle.sql":  # the chain files joined, with the preconditions
            (out / name).write_text(text)
    return refused


# --- upgrade --------------------------------------------------------------------------------------------------------

_TX = re.compile(r"^(BEGIN TRANSACTION;|COMMIT;)\s*$\n?", re.M)


def before_baseline(checkout: Checkout, chain: str, revision: str | None) -> bool:
    pin = BASELINE[chain]
    if revision is None:
        return True
    return pin not in {r.revision for r in checkout.scripts(chain).iterate_revisions(revision, "base")}


@dataclass
class Step:
    chain: str
    revision: str
    previous: str
    up: str
    down: str | None
    version_table: str


def steps(old: Checkout, new: Checkout) -> list[Step]:
    found: list[Step] = []
    refused: list[str] = []
    for chain in chains():
        if not new.has(chain):
            continue
        start, end = old.head(chain), new.head(chain)
        if start == end:
            continue
        if before_baseline(new, chain, start):
            refused.append(f"{chain} {start or 'base'}: before {chain}'s SQL Server baseline {BASELINE[chain]}")
            continue
        for rev in reversed(list(new.scripts(chain).iterate_revisions(end, start))):
            prev = str(rev.down_revision)
            if rev.revision in ONLINE_ONLY.get(chain, set()):
                refused.append(f"{chain} {rev.revision}: reads rows or inspects tables, so it cannot render offline")
                continue
            up = alembic_sql(new, chain, "upgrade", f"{prev}:{rev.revision}")
            if up.returncode:
                refused.append(f"{chain} {rev.revision} ({up.stderr.strip().splitlines()[-1][:160]})")
                continue
            if POSTGRES_ONLY.search(up.stdout):
                refused.append(
                    f"{chain} {rev.revision}: PostgreSQL SQL in op.execute; write it with the dialect helper"
                )
                continue
            down = alembic_sql(new, chain, "downgrade", f"{rev.revision}:{prev}")
            table = re.search(r"UPDATE (alembic_version\w*)", up.stdout)
            if table is None:
                raise SystemExit(f"{chain} {rev.revision}: the offline SQL records no version row")
            found.append(
                Step(
                    chain,
                    rev.revision,
                    prev,
                    _TX.sub("", up.stdout).strip(),
                    _TX.sub("", down.stdout).strip() if down.returncode == 0 else None,
                    table.group(1),
                )
            )
    if refused:
        raise Refused(
            "these revisions do not render for SQL Server; install the baseline of a release after them instead:\n  "
            + "\n  ".join(refused)
        )
    return found


def guard(version_table: str, expected: str) -> str:
    return (
        f"IF NOT EXISTS (SELECT 1 FROM dbo.{version_table} WHERE version_num = N'{expected}')\n"
        f"    THROW 50010, N'this step needs {version_table} at {expected}', 1;\nGO\n"
    )


def write_upgrade(old: Checkout, new: Checkout, out: Path) -> list[Step]:
    found = steps(old, new)
    out.mkdir(parents=True, exist_ok=True)
    head = (
        f"-- Ops AI schema upgrade for SQL Server, {old.ref} ({old.commit[:12]}) to {new.ref} ({new.commit[:12]}),\n"
        "-- generated by deploy/database/mssql.py; do not edit. Run as the migrator with sqlcmd -b. Each step checks\n"
        f"-- its version row, then runs in its own transaction; then run grants.sql from {new.ref}'s baseline.\n"
        "SET XACT_ABORT ON;\nGO\n\n"
    )
    up, down = [head], [head.replace("upgrade", "downgrade", 1)]
    for s in found:
        up.append(
            f"-- step {s.chain} {s.previous} -> {s.revision}  sha256 {sha256(s.up)}\n"
            + guard(s.version_table, s.previous)
            + f"BEGIN TRANSACTION;\nGO\n{s.up}\nCOMMIT;\nGO\n\n"
        )
    for s in reversed(found):
        if s.down is None:
            down.append(f"-- step {s.chain} {s.revision} -> {s.previous}: no downgrade; restore a backup\n\n")
            continue
        down.append(
            f"-- step {s.chain} {s.revision} -> {s.previous}  sha256 {sha256(s.down)}\n"
            + guard(s.version_table, s.revision)
            + f"BEGIN TRANSACTION;\nGO\n{s.down}\nCOMMIT;\nGO\n\n"
        )
    (out / "upgrade-roles.sql").write_text(
        head.replace("Run as the migrator", "Run in master by a server administrator", 1)
        + "-- No step needs a server administrator: SQL Server upgrades add no logins.\n"
    )
    (out / "upgrade.sql").write_text("".join(up))
    (out / "downgrade.sql").write_text("".join(down))
    write_sums(out)
    return found


# --- cli (schema.py --dialect mssql hands its arguments here) -------------------------------------------------------


def here() -> Checkout:
    root = GOLDEN.parents[3]
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    return Checkout(".", root, commit.stdout.strip() or "unversioned")


def run(a: argparse.Namespace) -> None:
    if a.cmd == "ddl":
        with exported(a.ref) as checkout:
            # The export's own models, through its own environment: this file runs there as a subprocess.
            if checkout.root != here().root:
                done = subprocess.run(
                    [str(checkout.root / ".venv" / "bin" / "python"), __file__, "ddl", str(a.out.resolve())],
                    cwd=checkout.root,
                    env={**checkout.env(OFFLINE_URL), "OPS_REF": checkout.ref, "OPS_COMMIT": checkout.commit},
                    check=False,
                )
                sys.exit(done.returncode)
            m = write_ddl(checkout, a.out)
        print(f"ddl: {a.out} at {m['ref']} ({m['commit'][:12]}) for SQL Server: {', '.join(sorted(m['files']))}")
    elif a.cmd == "upgrade-sql":
        with exported(a.old) as old, exported(a.new) as new:
            found = write_upgrade(old, new, a.out)
        print(f"upgrade-sql: {a.out}: {len(found)} SQL Server steps")
        for s in found:
            print(f"  {s.chain:<10} {s.previous} -> {s.revision}")
    elif a.cmd == "golden":
        refused = write_golden(here())
        print(f"golden: {GOLDEN.relative_to(GOLDEN.parents[3])}: {', '.join(sorted(p.name for p in GOLDEN.glob('*')))}")
        for r in refused:
            print(r)
    else:
        print(f"{a.cmd} DIALECT=mssql needs a server (c-345); nothing was checked.")
        sys.exit(2)


if __name__ == "__main__":
    # Inside an export, by run() above: compile that checkout's models with its own packages.
    import os

    m = write_ddl(
        Checkout(os.environ.get("OPS_REF", "."), Path.cwd(), os.environ.get("OPS_COMMIT", "")), Path(sys.argv[2])
    )
    print(f"ddl: {sys.argv[2]} at {m['ref']} ({m['commit'][:12]}) for SQL Server: {', '.join(sorted(m['files']))}")
