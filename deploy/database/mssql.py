"""The SQL Server and Azure SQL dialect of the schema tool (ADR docs/architecture/decisions/database-support.md).

    make db-ddl DIALECT=mssql OUT=<dir>                  roles.sql, one file per chain, bundle.sql, grants.sql, manifest
    make db-upgrade-sql DIALECT=mssql FROM=<ref> TO=<ref>  upgrade.sql and downgrade.sql from Alembic's offline SQL
    make db-ddl-golden                                    deploy/database/golden/mssql/ from this checkout's models

No server is needed. The baseline is compiled from each chain's store metadata (models.chain_metadata) with SQLAlchemy's
mssql dialect, because 53 of the 150 PostgreSQL migrations hold SQL that cannot run on SQL Server; a test holds the
metadata equal to what the migrations build. Each chain's baseline is stamped at its head, and only revisions after
BASELINE render for SQL Server. Isolation is a security policy per tenant-scoped table, generated from its markings by
ops_store.schema.security_ddl (by tenant, or by tenant and team for a team-owned one), the SQL Server form of the
forced row-level security those tables carry on PostgreSQL. Every file is a sqlcmd script (`sqlcmd -b -i`): GO
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

from ops_platform.store.lookups import LOOKUPS as PLATFORM_LOOKUPS
from ops_platform.store.lookups import SYSTEM_USER as PLATFORM_SYSTEM_USER
from ops_platform.store.lookups import Lookup, mssql_function
from ops_store.schema import MSSQL_COLLATION, MSSQL_PRECONDITIONS, MSSQL_SECURITY, mssql_full_text_ddl, security_ddl
from ops_store.schema import POSTGRES_ONLY as POSTGRES_ONLY_TABLE

GOLDEN = Path(__file__).resolve().parent / "golden" / "mssql"
OFFLINE_URL = "mssql+aioodbc://offline:offline@localhost:1/offline"
COLLATION = MSSQL_COLLATION
SECURITY = MSSQL_SECURITY
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
    # The run reconciler finds runs with nothing behind them across tenants and changes each in its own.
    "engine_runs": (("SELECT",), ()),
    "engine_steps": (("SELECT",), ()),
    # The retention sweep lists the tenants holding memories; it never reads what an agent remembers.
    "agent_memories": (("SELECT",), ("tenant_id",)),
    # Every background process writes its heartbeat; the Background page reads every team's jobs.
    "background_heartbeats": (("SELECT", "INSERT", "UPDATE", "DELETE"), ()),
    "background_jobs": (("SELECT",), ()),
    # The batch starter finds every tenant's pending rows, then starts each in its own tenant and team.
    "run_batches": (("SELECT",), ()),
    "run_batch_rows": (("SELECT",), ()),
    # The start-up catch-up finds every team whose default agent is its Ops Assistant (agents 0096).
    "team_default_agents": (("SELECT",), ()),
    # The start-up serving reload finds every tenant's published agents (agents 0107); never a name or a spec.
    "registry_agents": (("SELECT",), ("tenant_id", "id", "published_version", "paused")),
}
Grants = dict[str, tuple[tuple[str, ...], tuple[str, ...]]]
# Each chain's system principal (a user without a login its runtime user alone may impersonate) and what it reads, as
# that chain's migrations grant its BYPASSRLS role on PostgreSQL: the agents loops' role, and the outbox relays and
# documents' restart. Held equal to the PostgreSQL grants by test_model_parity.py.
SYSTEM_USERS: dict[str, tuple[str, Grants]] = {
    SYSTEM_CHAIN: (SYSTEM_USER, SYSTEM_READS),
    # files: the retention purge reads which snapshots were released (files_0014); the watch check process lists
    # watches with a check asked for, and the retention sweep deletes old watch events (files 20261124_0010).
    "files": (
        "ops_files_system",
        {
            "files_outbox": (("SELECT", "UPDATE", "DELETE"), ()),
            "files": (("SELECT",), ()),
            "file_watches": (("SELECT",), ()),
            "file_watch_events": (("SELECT", "DELETE"), ()),
        },
    ),
    # tools: the team-default catch-up, review hand-over and sign-in keep-alive listings, the relay and the secret
    # audit sweep (tools_0081).
    "tools": (
        "ops_tools_system",
        {
            # Columns only, as tools_0083 grants: a module's headers, sign-in and baseline can hold a credential.
            "team_defaults": (("SELECT",), ("tenant_id", "team_id", "version")),
            "tool_modules": (("SELECT",), ("tenant_id", "id", "team_id", "display_name")),
            "module_versions": (
                ("SELECT",),
                ("tenant_id", "module_id", "version", "status", "review_id", "published_by"),
            ),
            "module_approvals": (
                ("SELECT",),
                (
                    "tenant_id",
                    "module_id",
                    "id",
                    "status",
                    "review_id",
                    "decider_team",
                    "workflow_id",
                    "workflow_name",
                    "operations",
                    "environment",
                    "expires_at",
                    "justification",
                    "requested_by",
                    "requested_by_email",
                ),
            ),
            "service_outbox": (("SELECT", "UPDATE", "DELETE"), ()),
            "secret_audit": (("SELECT", "DELETE"), ()),
        },
    ),
    # kb: the relay, and the listing of every tenant holding a source that the schedule, the embedding backlog and the
    # start-up move read (kb_0011, kb_0014, kb_0026).
    "kb": (
        "ops_kb_system",
        {"kb_sources": (("SELECT",), ()), "kb_outbox": (("SELECT", "UPDATE", "DELETE"), ())},
    ),
    "documents": (
        "ops_documents_system",
        {
            "documents_outbox": (("SELECT", "UPDATE", "DELETE"), ()),
            "extractions": (("SELECT",), ()),
            "document_type_tests": (("SELECT",), ()),
            "documents_readings": (("SELECT",), ()),
        },
    ),
}
# A chain whose system user only its lookup functions run as (EXECUTE AS on each), with no login, no table grant and no
# IMPERSONATE for anyone, and those functions: platform's pre-tenant lookups (platform 0042). The read predicates pass
# the user; the runtime user gets SELECT on the functions alone, so it can name one exact key but list nothing across
# tenants.
LOOKUP_USERS: dict[str, tuple[str, tuple[Lookup, ...]]] = {"platform": (PLATFORM_SYSTEM_USER, PLATFORM_LOOKUPS)}


# Where each chain's portable migrations begin (2026-10-19, each chain's head that day). Revisions up to and including
# it are PostgreSQL history and never render for SQL Server; every later one is written with Alembic operations both
# run. SQL Server upgrades start from the first release whose bundle installs, the release cut; the pins
# move to its heads when it is cut, since no SQL Server install of an earlier release exists.
BASELINE = {
    "agents": "0070_engine_definitions_archived",
    "tools": "tools_0030_call_channel",
    "models": "models_0006",
    "kb": "kb_0009",
    # 0026 holds PostgreSQL-only SQL (DISTINCT ON, md5, a SECURITY DEFINER function), so it is history here too.
    "platform": "0026_workspace_owner",
    "files": "files_0009",
    "documents": "documents_0009",
}
# Foreign keys whose ON DELETE is NO ACTION on SQL Server, which refuses a table reached by two cascade paths from one
# delete (error 1785). A sign-in provider's delete reaches signin_grants by its own key and through
# signin_group_rules, so the rule key's SET NULL cannot stand there. The store clears a grant's rule before it deletes
# the rule (ops_platform.store.signin._keep_rules), and a provider's delete takes its grants with its rules.
NO_SECOND_CASCADE = {("signin_grants", "signin_grants_rule_id_fkey")}
DML = ("SELECT", "INSERT", "UPDATE", "DELETE")
_SI = ("SELECT", "INSERT")
_SIU = ("SELECT", "INSERT", "UPDATE")
_SID = ("SELECT", "INSERT", "DELETE")
# The tables on which a chain's runtime user holds less than DML, as its PostgreSQL tenant role does at the chain's
# head: (privileges, columns it may UPDATE alone). On PostgreSQL a transaction switches to the tenant role; SQL Server
# has one user, so the tenant role's narrowing is that user's. Append-only logs (platform 0002, tools 0044 and 0055,
# models 0012, agents 0021), no DELETE on a row a run or a person still points at, and agents' heartbeats written by
# the system user alone. A table a store with no role writes as the login (models' install tables) keeps DML. Held equal
# to PostgreSQL by test_model_parity.py.
RUNTIME_GRANTS: dict[str, Grants] = {
    "agents": {
        "background_heartbeats": ((), ()),
        "background_jobs": (_SID, ()),
        "case_events": (_SI, ()),
        "case_type_versions": (_SIU, ()),
        "case_types": (_SIU, ()),
        "cases": (_SIU, ()),
        "chat_search": (_SID, ()),
        "engine_runs": (_SIU, ()),
        "engine_steps": (_SIU, ()),
        "engine_waits": (_SID, ()),
        "engine_work": (_SIU, ()),
        "eval_cases": (_SID, ()),
        "eval_runs": (_SI, ()),
        "form_links": (_SIU, ()),
        "message_memory_use": (_SI, ()),
        # Rows no tenant can be named for (agents 0104): no store reads them, so no tenant transaction holds them.
        "model_call_records_unattributed": ((), ()),
        "ops_checkpoint_fences": (_SIU, ()),
        "poll_cursors": (_SIU, ()),
        "review_assignments": (_SI, ()),
        "run_batch_rows": (_SIU, ()),
        "run_batches": (_SIU, ()),
        "service_events": (_SIU, ()),
        "task_assists": (_SIU, ()),
        "task_type_versions": (_SIU, ()),
        "task_types": (_SIU, ()),
        "team_default_agents": (_SIU, ()),
        "template_copies": (_SIU, ()),
        "thread_budgets_unattributed": ((), ()),
        "thread_leases": (_SIU, ()),
        "timers": (_SIU, ()),
        # A trigger event is settled in place (agents 0089, 0091); what fired it is never rewritten.
        "trigger_events": (_SI, ("detail", "item", "outcome", "run_id")),
        "widget_deployments": (_SIU, ()),
        "widget_mint_key_audit": (_SI, ()),
        "widget_mint_keys": (_SIU, ()),
    },
    "documents": {"documents_template_copies": (_SIU, ())},
    "models": {"model_call_log": (_SI, ()), "model_key_tenants": (_SIU, ())},
    "platform": {"audit_entries": (_SI, ()), "policies": (_SIU, ())},
    "tools": {"connection_audit": (_SI, ()), "secret_audit": (_SI, ()), "service_outbox": (_SI, ())},
}


def runtime_grants(chain: str, table: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """What `chain`'s runtime user holds on `table`: DML unless RUNTIME_GRANTS narrows it."""
    return RUNTIME_GRANTS.get(chain, {}).get(table, (DML, ()))


def _runtime_table_grants(chain: str, table: str, user: str) -> list[str]:
    privileges, columns = runtime_grants(chain, table)
    if privileges == DML and not columns:
        return [f"GRANT {', '.join(DML)} ON dbo.{table} TO {user};"]
    # grants.sql runs again on every upgrade, so a database granted DML by an earlier release loses the rest here; a
    # table-wide REVOKE also takes the column grants, given back after it.
    out = [f"REVOKE {', '.join(p for p in DML if p not in privileges)} ON dbo.{table} FROM {user};"]
    if privileges:
        out.append(f"GRANT {', '.join(privileges)} ON dbo.{table} TO {user};")
    if columns:
        out.append(f"GRANT UPDATE ON dbo.{table} ({', '.join(columns)}) TO {user};")
    return out


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


def _in_key_order(t: sa.Table, fk: sa.ForeignKeyConstraint) -> None:
    """A foreign key's column pairs in the order of the key it references: SQL Server refuses another order (Msg 1776),
    while PostgreSQL takes any."""
    target = fk.referred_table
    pairs = {e.column.name: e.parent for e in fk.elements}
    keys = [list(target.primary_key.columns)]
    keys += [list(u.columns) for u in target.constraints if isinstance(u, sa.UniqueConstraint)]
    for key in keys:
        names = [c.name for c in key]
        if set(names) == set(pairs) and names != list(pairs):
            ordered = sa.ForeignKeyConstraint(
                [pairs[n] for n in names],
                [target.c[n] for n in names],
                name=fk.name,
                ondelete=fk.ondelete,
                onupdate=fk.onupdate,
            )
            ordered._creation_order = fk._creation_order  # pyright: ignore[reportPrivateUsage]
            t.constraints.discard(fk)
            for element in fk.elements:
                element.parent.foreign_keys.discard(element)
                t.foreign_keys.discard(element)
            t.append_constraint(ordered)
            return


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
    kept = [t for t in copies if not t.info.get(POSTGRES_ONLY_TABLE)]
    found = Chain(chain, list(sort_tables(kept)))
    found.omitted += [f"table {t.name} (PostgreSQL only)" for t in copies if t.info.get(POSTGRES_ONLY_TABLE)]
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
                twin = ix.dialect_options["mssql"]["where"]
                # A column the twin already filters is not filtered twice, so the index matches the migration's.
                said = re.sub(r'["\[\]]', "", str(twin)).lower() if twin is not None else ""
                where = [w for w in _not_null(ix.columns) if f"{w.left.name.lower()} is not null" not in said]
                if where:
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
            elif isinstance(con, sa.ForeignKeyConstraint):
                con.name = con.name or _key_name(t.name, columns, "fkey")
                # SQL Server has no RESTRICT; NO ACTION refuses the same deletes and updates, checked at once as well.
                for action in ("ondelete", "onupdate"):
                    if str(getattr(con, action) or "").upper() == "RESTRICT":
                        setattr(con, action, "NO ACTION")
                if (t.name, con.name) in NO_SECOND_CASCADE:
                    con.ondelete = "NO ACTION"
                _in_key_order(t, con)
            elif isinstance(con, sa.CheckConstraint) and con.name is None:
                refused.append(f"{chain} {t.name}: a CHECK constraint without a name")
    if refused:
        raise Refused("SQL Server DDL cannot be compiled from these models:\n  " + "\n  ".join(refused))
    return found


def _sql(element: Any) -> str:
    return str(element.compile(dialect=dialect())).strip()


def _column_type(column: sa.Column[Any]) -> str:
    return column.type.compile(dialect=dialect())


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


PRECONDITIONS = batches(MSSQL_PRECONDITIONS)


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
        lookup_user, lookups = LOOKUP_USERS.get(chain, (None, ()))
        system = SYSTEM_USERS[chain][0] if chain in SYSTEM_USERS else lookup_user
        if lookup_user:
            statements.append(f"IF USER_ID(N'{lookup_user}') IS NULL CREATE USER {lookup_user} WITHOUT LOGIN;")
        statements += [f"{s};" for s in security_ddl(chain, c.tables, column_type=_column_type, system_user=system)]
        statements += [f"{mssql_function(fn)};" for fn in lookups]
        # The bundle runs outside a transaction, as full-text DDL needs.
        statements += [s for t in c.tables for s in mssql_full_text_ddl(t)]
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
        "-- Each service's user: SELECT, INSERT, UPDATE, DELETE on its own tables, less where its PostgreSQL tenant\n",
        "-- role holds less (an append-only log, a row never deleted), and SELECT on its version table.\n",
        "-- No other permission, so it can create, alter or drop nothing, read no other service's tables, and\n",
        "-- every security policy applies to it. A chain's user may also impersonate that chain's system user (no\n",
        "-- login), which reads every tenant's rows of the tables and columns granted to it below, as on PostgreSQL.\n",
    ]
    statements: list[str] = []
    for c in chains_:
        user = c["runtimeRole"]
        statements.append(
            f"-- {c['name']}-service\n"
            f"IF USER_ID(N'{user}') IS NULL CREATE USER {user} FOR LOGIN {user} WITH DEFAULT_SCHEMA = dbo;"
        )
        statements.append(
            "\n".join(s for t in c["tables"] for s in _runtime_table_grants(c["name"], t, user))
            + f"\nGRANT SELECT ON dbo.{c['versionTable']} TO {user};"
        )
        if lookups := LOOKUP_USERS.get(c["name"], (None, ()))[1]:
            statements.append("\n".join(f"GRANT SELECT ON dbo.{fn.name} TO {user};" for fn in lookups))
        if c["name"] in SYSTEM_USERS:
            system, reads = SYSTEM_USERS[c["name"]]
            statements.append(f"IF USER_ID(N'{system}') IS NULL CREATE USER {system} WITHOUT LOGIN;")
            statements.append(
                "\n".join(
                    f"GRANT {', '.join(privileges)} ON dbo.{t}"
                    + (f" ({', '.join(columns)})" if columns else "")
                    + f" TO {system};"
                    for t, (privileges, columns) in reads.items()
                )
                + f"\nGRANT IMPERSONATE ON USER::{system} TO {user};"
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
                    # Alembic's own transaction lines are kept: an autocommit block (full-text DDL) runs between them,
                    # outside a transaction, as SQL Server requires.
                    up.stdout.strip(),
                    down.stdout.strip() if down.returncode == 0 else None,
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
        f"IF NOT EXISTS (SELECT 1 FROM dbo.{version_table} WHERE version_num = N'{expected}')\n"  # noqa: S608 - version table and revision are the chain's own names
        f"    THROW 50010, N'this step needs {version_table} at {expected}', 1;\nGO\n"
    )


def write_upgrade(old: Checkout, new: Checkout, out: Path) -> list[Step]:
    found = steps(old, new)
    out.mkdir(parents=True, exist_ok=True)
    head = (
        f"-- Ops AI schema upgrade for SQL Server, {old.ref} ({old.commit[:12]}) to {new.ref} ({new.commit[:12]}),\n"
        "-- generated by deploy/database/mssql.py; do not edit. Run as the migrator with sqlcmd -b. Each step checks\n"
        "-- its version row, then runs in its own transaction, apart from statements SQL Server refuses inside one\n"
        f"-- (full-text DDL), which run between its transactions; then run grants.sql from {new.ref}'s baseline.\n"
        "SET XACT_ABORT ON;\nGO\n\n"
    )
    up, down = [head], [head.replace("upgrade", "downgrade", 1)]
    for s in found:
        up.append(
            f"-- step {s.chain} {s.previous} -> {s.revision}  sha256 {sha256(s.up)}\n"
            + guard(s.version_table, s.previous)
            + f"{s.up}\n\n"
        )
    for s in reversed(found):
        if s.down is None:
            down.append(f"-- step {s.chain} {s.revision} -> {s.previous}: no downgrade; restore a backup\n\n")
            continue
        down.append(
            f"-- step {s.chain} {s.revision} -> {s.previous}  sha256 {sha256(s.down)}\n"
            + guard(s.version_table, s.revision)
            + f"{s.down}\n\n"
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
            # The export's own models, through its own environment and its own copy of this tool: this file's
            # imports name modules an older ref may not have (ops_platform.store.lookups), and its compile rules may
            # be newer than that ref's models.
            if checkout.root != here().root:
                tool = checkout.root / "deploy" / "database" / "mssql.py"
                if not tool.is_file():
                    raise SystemExit(f"{checkout.ref} has no deploy/database/mssql.py: it has no SQL Server baseline")
                done = subprocess.run(
                    [str(checkout.root / ".venv" / "bin" / "python"), str(tool), "ddl", str(a.out.resolve())],
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
        print(f"{a.cmd} DIALECT=mssql needs a server; nothing was checked.")
        sys.exit(2)


if __name__ == "__main__":
    # Inside an export, by run() above: compile that checkout's models with its own packages.
    import os

    m = write_ddl(
        Checkout(os.environ.get("OPS_REF", "."), Path.cwd(), os.environ.get("OPS_COMMIT", "")), Path(sys.argv[2])
    )
    print(f"ddl: {sys.argv[2]} at {m['ref']} ({m['commit'][:12]}) for SQL Server: {', '.join(sorted(m['files']))}")
