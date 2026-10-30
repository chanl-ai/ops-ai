"""SQL Server DDL compiled from the store models (c-344), checked with no server: the reviewed golden files under
deploy/database/golden/mssql/ equal what the models compile to now, isolation follows the table markings exactly,
a unique key over a nullable column admits the rows PostgreSQL admits, and an upgrade never replays PostgreSQL history.
Applying the DDL to a SQL Server is c-345.

A model change fails test_the_golden_file_is_what_the_models_compile_to, naming the chain's file; review the new DDL
and run `make db-ddl-golden`."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import importlib.util
import itertools

import mssql
import mssql_live
from models import chain_metadata, chains
from schema import Checkout

from ops_store.schema import isolation_kind, team_column, tenant_column

HERE = mssql.here()
READY = chains()


@pytest.fixture(scope="module")
def compiled() -> mssql.Compiled:
    return mssql.compile_all(HERE, chain_metadata, READY)


def _golden_names() -> list[str]:
    return sorted(p.name for p in mssql.GOLDEN.glob("*.sql"))


def test_the_golden_files_are_one_per_chain_plus_roles_and_grants(compiled: mssql.Compiled) -> None:
    expected = sorted(n for n in compiled.files if n != "bundle.sql")
    assert _golden_names() == expected, "golden files differ from the chains that compile; run make db-ddl-golden"


@pytest.mark.parametrize("name", _golden_names())
def test_the_golden_file_is_what_the_models_compile_to(compiled: mssql.Compiled, name: str) -> None:
    golden = (mssql.GOLDEN / name).read_text()
    assert compiled.files.get(name) == golden, (
        f"{name}: the SQL Server DDL compiled from the models differs from the reviewed golden file; "
        "review the change and run make db-ddl-golden"
    )


def test_a_model_change_shows_in_the_chain_s_ddl(compiled: mssql.Compiled) -> None:
    scratch = sa.MetaData()
    for m in chain_metadata("files"):
        for t in m.tables.values():
            t.to_metadata(scratch)
    scratch.tables["files"].append_column(sa.Column("added_by_test", sa.String(10)))
    changed = mssql.chain_tables("files", [scratch])
    files = next(t for t in changed.tables if t.name == "files")
    assert "added_by_test VARCHAR(10)" in mssql._sql(sa.schema.CreateTable(files))  # pyright: ignore[reportPrivateUsage]
    assert "added_by_test" not in compiled.files["06-files.sql"]


# --- US2: isolation follows the marker ------------------------------------------------------------------------------

_POLICY = re.compile(r"CREATE SECURITY POLICY ops_security\.(\w+?)_(tenant|isolation)\n(.*?);", re.S)


@pytest.mark.parametrize("chain", READY)
def test_every_marked_table_and_no_other_has_the_policy_its_markings_ask_for(
    compiled: mssql.Compiled, chain: str
) -> None:
    text = compiled.files[f"{chains().index(chain) + 1:02d}-{chain}.sql"]
    policies = {table: (kind, body) for table, kind, body in _POLICY.findall(text)}
    marked = {
        t.name: t for m in chain_metadata(chain) for t in m.tables.values() if isolation_kind(t) in ("team", "tenant")
    }
    assert {t: k for t, (k, _) in policies.items()} == {
        n: "isolation" if isolation_kind(t) == "team" else "tenant" for n, t in marked.items()
    }
    for table, (kind, body) in policies.items():
        t = marked[table]
        fn = f"ops_security.{chain}_{'team' if kind == 'isolation' else 'tenant'}"
        args = tenant_column(t).name + (f", {team_column(t).name}" if kind == "isolation" else "")
        assert f"ADD FILTER PREDICATE {fn}_read({args}) ON dbo.{table}," in body
        assert f"ADD BLOCK PREDICATE {fn}_write({args}) ON dbo.{table} AFTER INSERT" in body
        assert f"ADD BLOCK PREDICATE {fn}_write({args}) ON dbo.{table} AFTER UPDATE" in body
    system = f"USER_NAME() = N'{mssql.SYSTEM_USERS[chain][0]}'" if chain in mssql.SYSTEM_USERS else None
    for kind in {isolation_kind(t) for t in marked.values()}:
        read = re.search(rf"FUNCTION ops_security\.{chain}_{kind}_read .*?;", text, re.S)
        write = re.search(rf"FUNCTION ops_security\.{chain}_{kind}_write .*?;", text, re.S)
        assert read is not None and write is not None
        # Any login can call sp_set_session_context, so no session value opens another tenant's rows: only the system
        # principal does, and only in the chain that has one on PostgreSQL, where its grants say what it reads and
        # which columns it updates (the engine_work claim).
        for fn in (read.group(0), write.group(0)):
            assert "SESSION_CONTEXT(N'tenant_id')" in fn and "ops_system" not in fn
            assert (system is not None and system in fn) == (chain in mssql.SYSTEM_USERS)
        if kind == "team":
            # No team reads or writes a row with no team (c-507).
            assert "@team_id IS NULL" not in read.group(0) and "@team_id IS NULL" not in write.group(0)
            assert "SESSION_CONTEXT(N'team_id')" in write.group(0)


def test_each_system_principal_is_entered_only_by_its_own_chain(compiled: mssql.Compiled) -> None:
    grants = compiled.files["grants.sql"]
    for chain, (user, reads) in mssql.SYSTEM_USERS.items():
        assert f"CREATE USER {user} WITHOUT LOGIN;" in grants
        assert re.findall(rf"GRANT IMPERSONATE ON USER::{user} TO (\w+);", grants) == [f"ops_{chain}_runtime"]
        on = set(re.findall(rf"^GRANT .+? ON dbo\.(\w+)(?: \(.+?\))? TO {user};$", grants, re.M))
        assert on == set(reads), chain


def test_the_system_principal_has_postgresql_s_grants_and_only_agents_enters_it(compiled: mssql.Compiled) -> None:
    grants = compiled.files["grants.sql"]
    assert "CREATE USER ops_runtime_system WITHOUT LOGIN;" in grants
    assert re.findall(r"GRANT IMPERSONATE ON USER::ops_runtime_system TO (\w+);", grants) == ["ops_agents_runtime"]
    mine = re.findall(r"^GRANT (.+?) ON dbo\.(\w+)(?: \((.+?)\))? TO ops_runtime_system;$", grants, re.M)
    # What an agent remembers about a person stays unread: the retention sweep reads the tenant column alone.
    assert ("SELECT", "agent_memories", "tenant_id") in mine
    assert {t for _, t, _ in mine} == set(mssql.SYSTEM_READS)
    assert "mailboxes" not in {t for _, t, _ in mine}


# --- US3: nullable unique keys, partial indexes ---------------------------------------------------------------------


def _table(*extra: sa.Constraint | sa.Index) -> sa.Table:
    return sa.Table(
        "probe",
        sa.MetaData(),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("tenant_id", sa.String(64), nullable=False),
        sa.Column("token", sa.String(64)),
        *extra,
    )


def _ddl(table: sa.Table) -> str:
    (copy,) = mssql.chain_tables("probe", [table.metadata]).tables
    return "\n".join(
        [mssql._sql(sa.schema.CreateTable(copy))]  # pyright: ignore[reportPrivateUsage]
        + [mssql._sql(sa.schema.CreateIndex(ix)) for ix in copy.indexes]  # pyright: ignore[reportPrivateUsage]
    )


def test_a_unique_key_over_a_nullable_column_is_filtered_to_its_non_null_rows() -> None:
    ddl = _ddl(_table(sa.UniqueConstraint("tenant_id", "token")))
    assert "UNIQUE (tenant_id, token)" not in ddl
    assert "CREATE UNIQUE INDEX probe_tenant_id_token_key ON probe (tenant_id, token) WHERE token IS NOT NULL" in ddl


def test_a_unique_index_over_a_nullable_column_keeps_its_twin_and_adds_the_filter() -> None:
    open_ = sa.text("id <> ''")
    ddl = _ddl(_table(sa.Index("ux_probe", "token", unique=True, postgresql_where=open_, mssql_where=open_)))
    assert "CREATE UNIQUE INDEX ux_probe ON probe (token) WHERE id <> '' AND token IS NOT NULL" in ddl


def test_a_partial_index_without_its_mssql_twin_is_refused_by_name() -> None:
    with pytest.raises(mssql.Refused, match=r"probe probe\.ix_half: postgresql_where without its mssql_where twin"):
        _ddl(_table(sa.Index("ix_half", "token", postgresql_where=sa.text("token IS NULL"))))


def test_every_unique_key_in_the_golden_files_admits_postgresql_s_rows(compiled: mssql.Compiled) -> None:
    for chain in READY:
        for t in mssql.chain_tables(chain, chain_metadata(chain)).tables:
            for con in t.constraints:
                if isinstance(con, sa.UniqueConstraint):
                    assert not [c.name for c in con.columns if c.nullable], f"{t.name}.{con.name}: nullable key"
            for ix in t.indexes:
                where = ix.dialect_options["mssql"]["where"]
                for c in list[sa.Column[Any]](ix.columns) if ix.unique else []:
                    if c.nullable:
                        assert where is not None and f"{c.name} IS NOT NULL" in str(where), f"{t.name}.{ix.name}"


def test_no_postgresql_type_or_function_reaches_the_ddl(compiled: mssql.Compiled) -> None:
    for name, text in compiled.files.items():
        sql = "\n".join(line for line in text.splitlines() if not line.startswith("--"))
        # A PostgreSQL cast, not SQL Server's securable class (USER::name, SCHEMA::name).
        casts = r"(?<!\bUSER)(?<!\bSCHEMA)(?<!\bOBJECT)(?<!\bDATABASE)::\w"
        # RESTRICT is PostgreSQL's; SQL Server stops a bundle on it ("Incorrect syntax near the keyword 'RESTRICT'").
        found = re.findall(
            rf"TSVECTOR|to_tsvector|JSONB|\bnow\(\)|{casts}|\bTEXT\b|\bIMAGE\b|\bSERIAL\b|\bRESTRICT\b", sql
        )
        assert found == [], f"{name}: {found}"
    agents = compiled.files["01-agents.sql"]
    assert "created_at DATETIMEOFFSET NOT NULL" in agents and "BIT NOT NULL" in agents
    assert re.search(r"\bposition BIGINT NOT NULL IDENTITY", agents)


def test_every_foreign_key_names_its_target_key_in_that_key_s_order() -> None:
    # SQL Server refuses a foreign key whose columns are not a key's, in that key's order (Msg 1776); PostgreSQL takes
    # another order.
    wrong: list[str] = []
    for chain in chains():
        for t in mssql.chain_tables(chain, chain_metadata(chain)).tables:
            for fk in t.foreign_key_constraints:
                target = fk.referred_table
                named = [e.column.name for e in fk.elements]
                keys = [[c.name for c in target.primary_key.columns]]
                keys += [[c.name for c in u.columns] for u in target.constraints if isinstance(u, sa.UniqueConstraint)]
                # A filtered unique index cannot be referenced on SQL Server.
                keys += [
                    [c.name for c in ix.columns]
                    for ix in target.indexes
                    if ix.unique and ix.dialect_options["mssql"]["where"] is None
                ]
                if named not in keys:
                    wrong.append(f"{t.name}.{fk.name} -> {target.name} {named}")
    assert wrong == []


def test_the_drift_check_expects_what_the_bundle_creates() -> None:
    # The bundle leaves PostgreSQL-only columns out (kb_chunks.tsv, a tsvector); a drift check that expected them
    # would report every SQL Server install as missing them.
    columns, _ = mssql_live.expected()
    assert "tsv" not in columns["kb_chunks"] and "text" in columns["kb_chunks"]


def test_a_fresh_install_gets_the_memory_full_text_index_an_upgrade_gets(compiled: mssql.Compiled) -> None:
    # The same statement 0085 runs on an upgraded install, so both installs search memories alike.
    spec = importlib.util.spec_from_file_location(
        "memory_full_text", HERE.root / "services/agents-service/migrations/versions/0085_memory_full_text.py"
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert f"{migration.MSSQL_FULL_TEXT}\nGO\n" in compiled.files["01-agents.sql"]


# --- US5: upgrades ------------------------------------------------------------------------------------------------


class _At(Checkout):
    """This checkout, with one chain's head moved back."""

    def __init__(self, chain: str, head: str) -> None:
        super().__init__(f"{chain}@{head}", HERE.root, HERE.commit)
        self.moved = (chain, head)

    def head(self, chain: str) -> str | None:
        return self.moved[1] if chain == self.moved[0] else super().head(chain)


def test_an_upgrade_from_before_the_baseline_is_refused_by_name() -> None:
    with pytest.raises(mssql.Refused, match=r"files files_0008: before files's SQL Server baseline files_0009"):
        mssql.steps(_At("files", "files_0008"), HERE)


def test_an_upgrade_after_the_baseline_renders_guarded_sql_server_steps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(mssql.BASELINE, "files", "files_0008")
    found = mssql.write_upgrade(_At("files", "files_0008"), HERE, tmp_path)
    # One step per revision from the pin to the chain's head, whatever the head is today.
    steps = [(s.chain, s.previous, s.revision) for s in found]
    assert steps[0] == ("files", "files_0008", "files_0009")
    assert all(a[2] == b[1] for a, b in itertools.pairwise(steps))
    up = (tmp_path / "upgrade.sql").read_text()
    assert "IF NOT EXISTS (SELECT 1 FROM dbo.alembic_version_files WHERE version_num = N'files_0008')" in up
    assert "ALTER TABLE file_read_requests ALTER COLUMN document_type_id VARCHAR(64) NULL;" in up
    assert "SET XACT_ABORT ON;" in up


def test_a_statement_sql_server_runs_outside_a_transaction_stays_outside_one(tmp_path: Path) -> None:
    # 0085 creates a full-text catalog and index in an autocommit block; SQL Server refuses both inside a transaction.
    mssql.write_upgrade(_At("agents", "0084_memory_audit_team_required"), HERE, tmp_path)
    up = (tmp_path / "upgrade.sql").read_text()
    step = up[up.index("-> 0085_memory_full_text") : up.index("-- step agents 0085_memory_full_text")]
    open_transactions, at_full_text = 0, []
    for line in step.splitlines():
        open_transactions += line.startswith("BEGIN TRANSACTION;") - line.startswith("COMMIT;")
        if "CREATE FULLTEXT CATALOG" in line:
            at_full_text.append(open_transactions)
    assert at_full_text == [0], step


def test_an_upgrade_holding_postgresql_sql_is_refused_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    # Every revision after 0058 guards its PostgreSQL SQL by dialect, so the unguarded form is added to a real render.
    real = mssql.alembic_sql

    def unguarded(checkout: Checkout, chain: str, *args: str) -> subprocess.CompletedProcess[str]:
        done = real(checkout, chain, *args)
        done.stdout += "\nDO $$ BEGIN CREATE ROLE ops_runtime_tenant NOLOGIN; END $$;\n"
        return done

    monkeypatch.setitem(mssql.BASELINE, "files", "files_0008")
    monkeypatch.setattr(mssql, "alembic_sql", unguarded)
    with pytest.raises(mssql.Refused, match=r"files files_0009: PostgreSQL SQL in op.execute"):
        mssql.steps(_At("files", "files_0008"), HERE)
