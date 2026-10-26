"""Every record belongs to one team, and nothing crosses teams (c-507; docs/architecture/identity-and-tenancy.md "The
team is the workspace"). The lock, by failure mode:

- a table with a team column that is not marked team-owned, or whose team column allows no team: its rows escape the
  team policy or are readable by every team;
- a row-level policy that lets a row with no team be read, on PostgreSQL or SQL Server;
- a code path that means "every team" (`team_ids=None`, `teams=None`, `team_ids is None`) instead of one acting team;
- an allowlist entry that no longer matches anything, so the list only shrinks;
- a scan that finds nothing because it reads nothing.

Tables come from importing every module under services/*/src and packages/*/src that builds a table, so a new table
is covered without being listed. Tenant-held tables (people, sign-in, the account's own records) are allowlisted with
a reason; the tools tables are allowlisted until c-509 gives each team its own.
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path
from typing import Any

import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[2]
SOURCES = sorted(p for p in (*ROOT.glob("packages/*/src"), *ROOT.glob("services/*/src")) if p.is_dir())
# This checkout's sources first, as scripts/store_inventory.py does, so an export checks its own tables.
sys.path[:0] = [str(p) for p in SOURCES]

from ops_store.schema import TEAM_KEY, isolation_ddl, isolation_kind, mssql_predicates_ddl  # noqa: E402

TEAM_COLUMNS = ("team_id", "team")

# Tables that hold the account's people and records, not a team's work (rule: "The tenant holds people, not work").
TENANT_HELD = {
    "members": "a person's membership of a team, read by the account's access pages",
    "api_keys": "an account key names the team it acts in; the key belongs to the account's admins",
    "role_assignments": "a person's role in one team or in every team ('*', the account admin): the account's access",
    "audit_entries": "sign-in and membership events have no team; team pages filter on the acting team (c-507 Q1)",
    "service_outbox": "a relay read past the tenant by system_tx; each row carries its team, no read uses it",
    "files_outbox": "a relay read past the tenant by system_tx; each row carries its team, no read uses it",
    "documents_outbox": "a relay read past the tenant by system_tx; each row carries its team, no read uses it",
}
# Until c-509 gives each team its own tool modules (keys per team, its own policies): then this list is empty.
TOOLS_UNTIL_C509 = {
    "tool_modules": "tools per team: c-509",
    "connections": "tools per team: c-509",
    "send_policies": "tools per team: c-509",
    "send_checks": "tools per team: c-509",
}
# The account's background processes (docs/architecture/identity-and-tenancy.md, "The team is the workspace").
BACKGROUND = {
    "engine_definitions": "background process: the event workflows and the customer summary stay account-level; "
    "every other definition has a team (agents 0075)",
    "service_events": "background process: the update notices of the account-level event workflows have no team and "
    "show to every team; every other event carries its team",
}
ALLOWED_TABLES = TENANT_HELD | TOOLS_UNTIL_C509 | BACKGROUND

# Source lines allowed to mean "every team", each with its reason; the tools entries leave with c-509.
ALLOWED_BRANCHES = {
    "services/platform-service/src/ops_platform/roles.py": "a person's own grants across the teams they belong to",
    "services/tools-service/src/ops_tools/store/connections.py": "tools per team: c-509",
    "services/tools-service/src/ops_tools/store/secrets.py": "tools per team: c-509",
    "services/tools-service/src/ops_tools/secrets/routes.py": "tools per team: c-509",
    "packages/ops_engine/src/ops_engine/store/definitions.py": "background process: the engine's loops read every "
    "team's live definitions; a team reads its own and the background processes",
}

TABLE_BUILDERS = re.compile(r"\bsa\.Table\(|\b_child\(|\bTable\(")


def _modules() -> list[str]:
    out: list[str] = []
    for src in SOURCES:
        for path in sorted(src.rglob("*.py")):
            if "tests" in path.parts or "migrations" in path.parts or path.name == "__main__.py":
                continue
            if TABLE_BUILDERS.search(path.read_text()):
                out.append(".".join(path.relative_to(src).with_suffix("").parts).removesuffix(".__init__"))
    return out


def _tables() -> dict[str, sa.Table]:
    found: dict[str, sa.Table] = {}
    for name in _modules():
        try:
            mod = importlib.import_module(name)
        except Exception as e:  # a module that cannot import on its own (an optional driver) holds no table here
            if "No module named" in str(e):
                continue
            raise
        for value in vars(mod).values():
            if isinstance(value, sa.Table):
                table: sa.Table = value  # pyright: ignore[reportUnknownVariableType]
                found.setdefault(table.name, table)
            elif isinstance(value, sa.MetaData):
                for t in value.tables.values():
                    found.setdefault(t.name, t)
    return found


TABLES = _tables()


def _team_column(t: sa.Table) -> sa.Column[Any] | None:
    return next((c for c in t.c if c.name in TEAM_COLUMNS), None)


def test_the_scan_reads_the_tables_it_guards() -> None:
    assert len(TABLES) > 100, len(TABLES)
    assert {"engine_runs", "thread_events", "tool_modules", "kb_bases", "files"} <= set(TABLES)


def test_every_table_with_a_team_column_is_team_owned_with_a_team_on_every_row() -> None:
    problems: list[str] = []
    for name, t in sorted(TABLES.items()):
        column = _team_column(t)
        if column is None or name in ALLOWED_TABLES:
            continue
        if not isinstance(t.info.get(TEAM_KEY), str):
            problems.append(f"{name}: has {column.name} but is not marked team_owned")
        if column.nullable:
            problems.append(f"{name}: {column.name} allows a row with no team")
    assert problems == [], "\n".join(problems)


def test_no_policy_reads_a_row_with_no_team() -> None:
    problems: list[str] = []
    for name, t in sorted(TABLES.items()):
        if isolation_kind(t) != "team":
            continue
        team = t.info[TEAM_KEY]
        if any(f"{team} IS NULL" in stmt for stmt in isolation_ddl(t, "postgresql")):
            problems.append(f"{name}: PostgreSQL policy reads rows with no team")
        mssql = mssql_predicates_ddl("lock", [t], column_type=lambda _column: "NVARCHAR(64)", system_user=None)
        if any("@team_id IS NULL" in stmt for stmt in mssql):
            problems.append(f"{name}: SQL Server predicate reads rows with no team")
    assert problems == [], "\n".join(problems)


TEAM_NAMES = ("team_ids", "teams")


def _name(node: ast.expr) -> str:
    return node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else ""


def _every_team_branches(path: Path) -> list[str]:
    """`team_ids=None` / `teams=None` passed or defaulted, a `teams` / `team_ids` parameter that may be None, a check of
    either against None, and `sa.true() if team is None` (no team selected reads every team)."""
    hits: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.IfExp) and isinstance(node.test, ast.Compare) and isinstance(node.body, ast.Call):
            test = node.test
            if (
                _name(node.body.func) == "true"
                and len(test.ops) == 1
                and isinstance(test.ops[0], ast.Is)
                and _name(test.left) in ("team", *TEAM_NAMES)
                and isinstance(test.comparators[0], ast.Constant)
                and test.comparators[0].value is None
            ):
                hits.append(f"sa.true() if {_name(test.left)} is None")
        if isinstance(node, ast.keyword) and node.arg in ("team_ids", "teams"):
            if isinstance(node.value, ast.Constant) and node.value.value is None:
                hits.append(f"{node.arg}=None")
        elif isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Is | ast.IsNot):
            right = node.comparators[0]
            if _name(node.left) in TEAM_NAMES and isinstance(right, ast.Constant) and right.value is None:
                hits.append(f"{_name(node.left)} is None")
        elif (
            isinstance(node, ast.arg)
            and node.arg in TEAM_NAMES
            and node.annotation is not None
            and "None" in ast.unparse(node.annotation)
        ):
            hits.append(f"{node.arg}: {ast.unparse(node.annotation)}")
        if isinstance(node, ast.arguments):
            for arg, default in zip(node.args[len(node.args) - len(node.defaults) :], node.defaults, strict=True):
                if arg.arg in ("team_ids", "teams") and isinstance(default, ast.Constant) and default.value is None:
                    hits.append(f"{arg.arg}: ... = None")
            for arg, kw_default in zip(node.kwonlyargs, node.kw_defaults, strict=True):
                if (
                    arg.arg in ("team_ids", "teams")
                    and isinstance(kw_default, ast.Constant)
                    and kw_default.value is None
                ):
                    hits.append(f"{arg.arg}: ... = None")
    return hits


def test_no_code_path_means_every_team() -> None:
    problems: list[str] = []
    for src in SOURCES:
        for path in sorted(src.rglob("*.py")):
            rel = path.relative_to(ROOT).as_posix()
            if "tests" in path.parts or rel in ALLOWED_BRANCHES:
                continue
            problems += [f"{rel}: {hit}" for hit in sorted(set(_every_team_branches(path)))]
    assert problems == [], "\n".join(problems)


def test_the_allowlists_only_name_what_still_exists() -> None:
    stale = [name for name in ALLOWED_TABLES if name not in TABLES or _team_column(TABLES[name]) is None]
    stale += [rel for rel in ALLOWED_BRANCHES if not (ROOT / rel).exists() or not _every_team_branches(ROOT / rel)]
    assert stale == [], stale
