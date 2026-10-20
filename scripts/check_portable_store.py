"""Refuses storage code that would run on PostgreSQL and not on SQL Server, the two supported databases
(docs/architecture/decisions/database-support.md):

  sql   database-specific code outside ops_store, in source and migrations: RETURNING, ON CONFLICT, SKIP LOCKED,
        advisory locks, JSONB operators and the JSONB type in SQL text; the same built with SQLAlchemy Core
        (on_conflict_*, a dialect's own insert); a row lock (with_for_update, which renders nothing on SQL Server);
        the host-dependent clock functions (func.now, make_interval, date_trunc); and postgresql_* index options,
        except a postgresql_where given with its mssql_where twin.
  meta  table metadata SQL Server refuses: a key column (primary key, unique, indexed or a foreign key) of unbounded
        text, and a table, column, index or constraint name over 60 characters.

What is there today is listed in portable-baseline.txt, so only new code is a finding. The gate (verify-staged and
make python-verify) runs `--strict`, and `--commits`: a commit that raises a baseline row carries a
`Standards-exception:` trailer the orchestrator approved. ops_store.dialect holds each database's form.

  uv run python scripts/check_portable_store.py            # findings, exit 0
  uv run python scripts/check_portable_store.py --strict   # exit 1 when there is a finding
  uv run python scripts/check_portable_store.py --commits  # exit 1 when a commit raised the baseline without a trailer
  uv run python scripts/check_portable_store.py --update   # rewrite the baseline to today's findings
"""

from __future__ import annotations

import ast
import importlib
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "portable-baseline.txt"
SRC_ROOTS = sorted([*ROOT.glob("packages/*/src"), *ROOT.glob("services/*-service/src")])
# The store seam is where database-specific SQL belongs: each dialect's version of a query lives there.
SEAM = ROOT / "packages" / "ops_store"
MAX_NAME = 60

# Constructs found in SQL text the code passes to the database.
TEXT = [
    ("RETURNING", re.compile(r"\bRETURNING\b", re.IGNORECASE)),
    ("ON CONFLICT", re.compile(r"\bON\s+CONFLICT\b", re.IGNORECASE)),
    ("SKIP LOCKED", re.compile(r"\bSKIP\s+LOCKED\b", re.IGNORECASE)),
    ("advisory lock", re.compile(r"\bpg_(try_)?advisory_", re.IGNORECASE)),
    ("JSONB operator", re.compile(r"->>|#>>|@>|<@|\?\||\?&|\bjsonb_\w+\s*\(", re.IGNORECASE)),
]
# Text is read as SQL only when it reads like a statement; a regular expression's `?|` is not a JSONB operator.
SQL_SHAPE = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|WHERE|FROM|RETURNING|CONFLICT)\b", re.IGNORECASE)
# The same constructs built with SQLAlchemy Core.
ADVISORY_NAME = re.compile(r"^pg_(try_)?advisory_")
# A Postgres-only option that is portable when the same call gives SQL Server its own form: a partial index and a
# filtered index with the same simple predicate hold the same rows (c-342).
TWINS = {"postgresql_where": "mssql_where"}
# Core's returning() is portable (OUTPUT on SQL Server); RETURNING written in SQL text is not.
CALLS = {
    "on_conflict_do_nothing": "ON CONFLICT",
    "on_conflict_do_update": "ON CONFLICT",
    "with_for_update": "row lock",
}
# func.<name> that reads the host's clock or exists on PostgreSQL alone; ops_store.dialect has db_now and db_after.
CLOCK = {"now", "make_interval", "date_trunc", "clock_timestamp", "julianday"}
DIALECT_INSERT = {"postgresql", "sqlite"}


def docstrings(tree: ast.AST) -> set[int]:
    return {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }


def sql_findings(source: str) -> list[tuple[int, str]]:
    """(line, construct) for each Postgres-only construct in one file's code; docstrings and comments are not code."""
    tree = ast.parse(source)
    docs = docstrings(tree)
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docs
            and SQL_SHAPE.search(node.value)
        ):
            out += [(node.lineno, name) for name, pattern in TEXT if pattern.search(node.value)]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in CALLS:
            out.append((node.lineno, CALLS[node.func.attr]))
        # The same constructs built from names: `sa.func.pg_try_advisory_xact_lock(...)` and the `JSONB` column type.
        if isinstance(node, (ast.Attribute, ast.Name)):
            name = node.attr if isinstance(node, ast.Attribute) else node.id
            if ADVISORY_NAME.match(name):
                out.append((node.lineno, "advisory lock"))
            if name == "JSONB":
                out.append((node.lineno, "JSONB type"))
        if isinstance(node, ast.Attribute) and node.attr in CLOCK and _named(node.value) == "func":
            out.append((node.lineno, "database clock"))
        if isinstance(node, ast.Attribute) and node.attr == "insert" and _named(node.value) in DIALECT_INSERT:
            out.append((node.lineno, "dialect insert"))
        if (
            isinstance(node, ast.ImportFrom)
            and node.module in {f"sqlalchemy.dialects.{d}" for d in DIALECT_INSERT}
            and any(a.name == "insert" for a in node.names)
        ):
            out.append((node.lineno, "dialect insert"))
        # Dialect options on an index or table: postgresql_where (a partial index), postgresql_using (an index type).
        # A partial index with its SQL Server twin (mssql_where, a filtered index) holds the same rows on both.
        if isinstance(node, ast.Call):
            given = {k.arg for k in node.keywords}
            out += [
                (node.lineno, f"{k.arg} option")
                for k in node.keywords
                if (k.arg or "").startswith("postgresql_") and not (k.arg in TWINS and TWINS[k.arg] in given)
            ]
        if isinstance(node, ast.Call) and any(
            k.arg == "skip_locked" and isinstance(k.value, ast.Constant) and k.value.value is True
            for k in node.keywords
        ):
            out.append((node.lineno, "SKIP LOCKED"))
    return sorted(set(out))


def _named(node: ast.expr) -> str | None:
    return node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else None


# Migrations build the schema each database must accept, so they are read too.
MIGRATIONS = sorted(ROOT.glob("services/*-service/migrations/versions"))


def sql_sources() -> list[Path]:
    trees = [*SRC_ROOTS, *MIGRATIONS]
    return sorted(p for src in trees for p in src.rglob("*.py") if SEAM not in p.parents)


def is_store(path: Path) -> bool:
    return "store" in path.parts or path.name == "store.py" or "ops_checkpointer" in path.parts


def store_modules() -> list[str]:
    out: list[str] = []
    for src in SRC_ROOTS:
        for p in sorted(src.rglob("*.py")):
            if is_store(p.relative_to(src)) and p.name != "__init__.py":
                out.append(".".join(p.relative_to(src).with_suffix("").parts))
    return out


def tables() -> list[tuple[str, sa.Table]]:
    """(module, table) for each table a store module defines."""
    # Keyed by top-level package and name: a module that imports another's table must not count it twice, and two
    # services may each own a table of the same name.
    seen: dict[tuple[str, str], tuple[str, sa.Table]] = {}
    for name in store_modules():
        mod = importlib.import_module(name)
        for value in vars(mod).values():
            if isinstance(value, sa.Table):
                seen.setdefault((name.split(".")[0], value.fullname), (name, value))  # pyright: ignore[reportUnknownArgumentType]
    return sorted(seen.values(), key=lambda mt: (mt[0], mt[1].name))


def is_key(table: sa.Table, column: sa.Column[object]) -> bool:
    if column.primary_key or column.unique or column.index or column.foreign_keys:
        return True
    indexed = [i.columns for i in table.indexes]
    unique = [c.columns for c in table.constraints if isinstance(c, sa.UniqueConstraint)]
    return any(column.name in cols for cols in [*indexed, *unique])


def unbounded(column: sa.Column[object]) -> bool:
    t = column.type
    return isinstance(t, sa.Text) or (isinstance(t, sa.String) and t.length is None)


def meta_findings(found: Iterable[tuple[str, sa.Table]]) -> list[tuple[str, str]]:
    """(module, finding) for each key column of unbounded text and each name over MAX_NAME characters."""
    out: list[tuple[str, str]] = []
    for module, table in found:
        names = [("table", table.name)]
        for column in table.columns:
            names.append(("column", f"{table.name}.{column.name}"))
            if is_key(table, column) and unbounded(column):
                out.append((module, f"unbounded key column {table.name}.{column.name}"))
        names += [("index", str(i.name)) for i in table.indexes if i.name]
        names += [("constraint", str(c.name)) for c in table.constraints if isinstance(c.name, str)]
        for kind, full in names:
            if len(full.split(".")[-1]) > MAX_NAME:
                out.append((module, f"{kind} name over {MAX_NAME} characters {full}"))
    return out


def current() -> tuple[Counter[str], dict[str, list[str]]]:
    """Counts by baseline key, and where each one is, for the warnings."""
    counts: Counter[str] = Counter()
    where: dict[str, list[str]] = {}
    for path in sql_sources():
        rel = path.relative_to(ROOT).as_posix()
        for line, construct in sql_findings(path.read_text()):
            key = f"sql {rel} {construct}"
            counts[key] += 1
            where.setdefault(key, []).append(f"{rel}:{line}")
    for module, finding in meta_findings(tables()):
        key = f"meta {module} {finding}"
        counts[key] += 1
        where.setdefault(key, []).append(module)
    return counts, where


def read_baseline(text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            n, key = line.split(" ", 1)
            counts[key] = int(n)
    return counts


def warnings(now: Counter[str], base: Counter[str], where: dict[str, list[str]]) -> list[str]:
    out: list[str] = []
    for key, n in sorted(now.items()):
        if n > base.get(key, 0):
            kind, _, rest = key.partition(" ")
            construct = rest.split(" ", 1)[1]
            fix = (
                "bound the column (sa.String(n)) or shorten the name"
                if kind == "meta"
                else "give every supported database its own form of the index, or do without it"
                if construct.endswith(" option")
                else "use ops_store.dialect (locked, claim, upsert, insert_ignore, lock_key, db_now, db_after)"
            )
            out.append(f"WARNING {', '.join(where[key])}: {rest.split(' ', 1)[1]} ({n} > {base.get(key, 0)}); {fix}")
    return out


def render(counts: Counter[str]) -> str:
    head = [
        f"# {sum(counts.values())} findings: code and metadata outside ops_store that would not run on SQL Server"
        " (scripts/check_portable_store.py). A row may only fall; raising one needs a Standards-exception: trailer.",
    ]
    head.append(
        "# Burned down by ops_store.dialect: row lock and SKIP LOCKED -> locked/claim, database clock -> db_now and"
        " db_after, dialect insert and ON CONFLICT -> upsert/insert_ignore, advisory lock -> lock_key."
    )
    lines: list[str] = []
    for owner in sorted({_owner(k) for k in counts}):
        rows = sorted((k, n) for k, n in counts.items() if _owner(k) == owner)
        lines += [f"# {owner}: {sum(n for _, n in rows)}", *(f"{n} {k}" for k, n in rows)]
    return "\n".join([*head, *lines]) + "\n"


def _owner(key: str) -> str:
    """The service or package a baseline row belongs to: `services/x-service` or `packages/x` (or the module's top
    package for a metadata row)."""
    path = key.split(" ")[1]
    parts = path.split("/")
    return "/".join(parts[:2]) if parts[0] in ("services", "packages") else path.split(".")[0]


# The commit before the first one this check reads: from here on, a commit that raises a baseline row needs a trailer.
BASELINE_BEGAN = "ff31407eb261038374fc5c7fda556b40a519fcef"
TRAILER = "Standards-exception:"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def raised(before: str, after: str) -> list[str]:
    """Baseline rows whose count is higher in `after` than in `before`, new rows included."""
    old, new = read_baseline(before), read_baseline(after)
    return sorted(f"{key} ({old.get(key, 0)} -> {n})" for key, n in new.items() if n > old.get(key, 0))


def commit_problems() -> list[str]:
    """Commits after BASELINE_BEGAN that raise a row of portable-baseline.txt without a Standards-exception: trailer.
    An export without history (verify-head's one-commit copy) has nothing to check; verify-staged runs it on the
    repository."""
    probe = ["git", "cat-file", "-e", f"{BASELINE_BEGAN}^{{commit}}"]
    if subprocess.run(probe, cwd=ROOT, capture_output=True, check=False).returncode:
        return []
    out: list[str] = []
    for sha in _git("log", "--format=%H", f"{BASELINE_BEGAN}..HEAD", "--", BASELINE.name).split():
        before = subprocess.run(
            ["git", "show", f"{sha}^:{BASELINE.name}"], cwd=ROOT, capture_output=True, text=True, check=False
        ).stdout
        rows = raised(before, _git("show", f"{sha}:{BASELINE.name}"))
        message = _git("log", "-1", "--format=%B", sha)
        if rows and not any(line.startswith(TRAILER) for line in message.splitlines()):
            out += [f"trailer {sha[:8]} raises `{row}` with no {TRAILER} trailer" for row in rows]
    return out


def main() -> int:
    if "--commits" in sys.argv:
        missing = commit_problems()
        sys.stdout.write(
            "\n".join(missing) + "\n"
            if missing
            else f"Every baseline rise since {BASELINE_BEGAN[:8]} carries {TRAILER}\n"
        )
        return 1 if missing else 0
    now, where = current()
    if "--update" in sys.argv:
        BASELINE.write_text(render(now))
        sys.stdout.write(f"check_portable_store: baseline has {sum(now.values())} findings\n")
        return 0
    base = read_baseline(BASELINE.read_text()) if BASELINE.exists() else Counter[str]()
    found = warnings(now, base, where)
    for line in found:
        sys.stderr.write(line + "\n")
    fell = sum(base.values()) - sum(min(n, base[k]) for k, n in now.items())
    note = f"; {fell} fixed since the baseline, run --update to lower it" if fell else ""
    sys.stdout.write(f"check_portable_store: {len(found)} warnings{note}\n")
    return 1 if found and "--strict" in sys.argv else 0


if __name__ == "__main__":
    raise SystemExit(main())
