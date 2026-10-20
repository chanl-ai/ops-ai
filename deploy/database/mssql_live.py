"""SQL Server against a live server (c-345): install the SQL Server bundle the way a DBA does (sqlcmd), compare the
database with the store models, and read its tenant security predicates. It runs where ODBC Driver 18 and sqlcmd are,
the test image (deploy/fly/Dockerfile, target test-mssql), never a laptop (docs/deploy/fly.md, SQL Server test machine).

    python deploy/database/mssql_live.py install --dir <make db-ddl DIALECT=mssql output> --database <name>
    python deploy/database/mssql_live.py drift --database <name>      missing, extra and different; exit 1 on any

The server is OPS_MSSQL_SERVER (host,port) and its administrator's password MSSQL_SA_PASSWORD; neither is printed.
"""

from __future__ import annotations

import argparse
import os
import secrets
import string
import subprocess
import sys
from pathlib import Path
from typing import Any

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parent))
from models import chain_metadata, chains

from ops_store.schema import tenant_scoped

SQLCMD = "/opt/mssql-tools18/bin/sqlcmd"
SECURITY = "ops_security"


def server() -> str:
    return os.environ.get("OPS_MSSQL_SERVER", "host.docker.internal,14330")


def password() -> str:
    return os.environ["MSSQL_SA_PASSWORD"]


def sqlcmd(database: str, script: Path, variables: dict[str, str] | None = None) -> None:
    # -I: QUOTED_IDENTIFIER on. sqlcmd leaves it off, and SQL Server refuses a filtered index (the bundle has them)
    # without it; the bundle does not set it itself yet (reported to c-344).
    argv = [SQLCMD, "-S", server(), "-U", "sa", "-C", "-b", "-I", "-d", database, "-i", str(script)]
    for k, v in (variables or {}).items():
        argv += ["-v", f"{k}={v}"]
    run = subprocess.run(
        argv, env={**os.environ, "SQLCMDPASSWORD": password()}, capture_output=True, text=True, check=False
    )
    if run.returncode:
        raise SystemExit(f"{script.name}: sqlcmd failed\n{run.stdout[-3000:]}{run.stderr[-1500:]}")


def engine(database: str) -> sa.Engine:
    host, port = server().split(",")
    url = sa.URL.create(
        "mssql+pyodbc",
        username="sa",
        password=password(),
        host=host,
        port=int(port),
        database=database,
        query={"driver": "ODBC Driver 18 for SQL Server", "TrustServerCertificate": "yes"},
    )
    return sa.create_engine(url)


def login_password() -> str:
    """A password that meets SQL Server's policy: every character class, never printed."""
    # No "=" or quote: sqlcmd -v takes name=value.
    pools = (string.ascii_uppercase, string.ascii_lowercase, string.digits, "#+-_.")
    chars = [secrets.choice(p) for p in pools for _ in range(5)]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def install(folder: Path, database: str) -> None:
    """roles.sql in master (the database and its logins), then bundle.sql and grants.sql in the database, as a DBA
    runs them. sa stands in for the migrator here: the test database is dropped after the run."""
    logins = {f"{c}_password": login_password() for c in ["ops_migrator", *(f"ops_{c}_runtime" for c in chains())]}
    sqlcmd("master", folder / "roles.sql", {"database": database, **logins})
    sqlcmd(database, folder / "bundle.sql")
    sqlcmd(database, folder / "grants.sql")


def drop(database: str) -> None:
    """The test database and the server logins roles.sql made for it; logins are server-wide, so they go too."""
    with engine("master").connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.execute(
            sa.text(
                f"IF DB_ID(N'{database}') IS NOT NULL BEGIN ALTER DATABASE [{database}] SET SINGLE_USER "
                f"WITH ROLLBACK IMMEDIATE; DROP DATABASE [{database}]; END"
            )
        )
        for login in ["ops_migrator", *(f"ops_{c_}_runtime" for c_ in chains())]:
            c.execute(sa.text(f"IF SUSER_ID(N'{login}') IS NOT NULL DROP LOGIN [{login}]"))


def expected() -> tuple[dict[str, set[str]], set[str]]:
    """Each table's columns from the store models, and the tables a tenant policy must cover."""
    columns: dict[str, set[str]] = {}
    scoped: set[str] = set()
    for chain in chains():
        for md in chain_metadata(chain):
            for t in md.tables.values():
                # Columns mssql.py leaves out on SQL Server (PostgreSQL-only, such as a tsvector) are not expected.
                columns[t.name] = {c.name for c in t.columns if not c.info.get("mssql_omit")}
                if tenant_scoped(t):
                    scoped.add(t.name)
    return columns, scoped


def drift(database: str) -> list[str]:
    want, scoped = expected()
    eng = engine(database)
    found: list[str] = []
    with eng.connect() as c:
        inspector = sa.inspect(c)
        have = {t for t in inspector.get_table_names(schema="dbo") if not t.startswith("alembic_version")}
        for t in sorted(set(want) - have):
            found.append(f"missing  TABLE {t}")
        for t in sorted(have - set(want)):
            found.append(f"extra    TABLE {t}")
        for t in sorted(set(want) & have):
            cols = {col["name"] for col in inspector.get_columns(t, schema="dbo")}
            for name in sorted(want[t] - cols):
                found.append(f"missing  COLUMN {t}.{name}")
            for name in sorted(cols - want[t]):
                found.append(f"extra    COLUMN {t}.{name}")
        found += predicates(c, scoped)
    eng.dispose()
    return found


def predicates(c: Any, scoped: set[str]) -> list[str]:
    """Every tenant-scoped table needs its policy: a filter predicate and block predicates after insert and update,
    enabled. Read from sys.security_policies and sys.security_predicates."""
    rows = c.execute(
        sa.text(
            "SELECT OBJECT_NAME(pr.target_object_id) AS target, p.is_enabled, pr.predicate_type_desc AS kind, "
            "pr.operation_desc AS operation, pr.predicate_definition AS definition "
            "FROM sys.security_policies p JOIN sys.security_predicates pr ON pr.object_id = p.object_id"
        )
    ).mappings()
    held: dict[str, set[tuple[str, str]]] = {}
    for r in rows:
        if r["is_enabled"] and SECURITY in str(r["definition"]):
            held.setdefault(str(r["target"]), set()).add((str(r["kind"]), str(r["operation"] or "")))
    need = {("FILTER", ""), ("BLOCK", "AFTER INSERT"), ("BLOCK", "AFTER UPDATE")}
    out: list[str] = []
    for table in sorted(scoped):
        lacking = need - held.get(table, set())
        if lacking:
            out.append(f"missing  POLICY {table}: " + ", ".join(f"{k} {o}".strip() for k, o in sorted(lacking)))
    for table in sorted(set(held) - scoped):
        out.append(f"extra    POLICY {table}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("install")
    i.add_argument("--dir", type=Path, required=True)
    i.add_argument("--database", required=True)
    d = sub.add_parser("drift")
    d.add_argument("--database", required=True)
    x = sub.add_parser("drop")
    x.add_argument("--database", required=True)
    a = ap.parse_args()
    if a.cmd == "install":
        install(a.dir, a.database)
        print(f"install: {a.database} from {a.dir} on SQL Server")
    elif a.cmd == "drop":
        drop(a.database)
    else:
        found = drift(a.database)
        print("\n".join(found) or "drift: none")
        print(f"drift: {len(found)} difference(s) from the store models and their tenant policies")
        sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
