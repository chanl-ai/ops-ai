"""Every read of a team-owned table names the caller's team (c-407). A table marked `TEAM_OWNED` (or
`team_owned_via`) in its `info` is read only inside a function that also calls `team_visible(<table>)`, or
`any_team(<table>, reason)` where a lookup must see every team to decide a refusal. A store that selects from the table
without one shows another team's records, which is how agents, skills and guardrails leaked on staging (2026-10-20).

The scan is of source, like test_service_engines.py: a read is a `select(...)`, `.select_from(...)` or `.join(...)` that
names the table, or `<table>.select()`. Every other table with a team column is listed in NOT_YET_MARKED, which may
only shrink: its reads are scoped by explicit team arguments today, checked from outside by
scripts/team_isolation_probe.py, and each one moves to the marker and the helper in turn.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCES = ("services/*/src/**/*.py", "packages/*/src/**/*.py")
HELPERS = {"team_visible", "any_team"}
MARKERS = ("TEAM_OWNED", "team_owned(", "team_owned_via(")
TEAM_COLUMNS = {"team_id", "team"}

# Tables with a team column whose reads take the team as an argument instead of the helper. Remove a name when its
# table is marked; the test fails on a name that is marked or gone, so the list only shrinks.
NOT_YET_MARKED = {
    # agents-service: work records, scoped by the acting team passed in, or by thread
    "cases",
    "chat_attachments",
    "chat_search",
    "thread_events",
    "graph_threads",
    "graph_runs",
    "mailboxes",
    "agent_memories",
    "review_decisions",
    "review_approvals",
    "service_events",
    "team_default_agents",
    "trigger_events",
    "widget_deployments",
    "deployments",
    # ops_engine: runs and definitions, scoped by the team passed in
    "engine_definitions",
    "engine_runs",
    # tools-service
    "connections",
    "tool_modules",
    "send_policies",
    "send_checks",
    # files-service and documents-service: their `team` column
    "files",
    "file_blobs",
    "file_read_requests",
    "extractions",
    "document_types",
    "document_type_tests",
    "document_type_examples",
    # platform-service: identity and administration, read by team and role through platform's own routes
    "members",
    "api_keys",
    "audit_entries",
    "role_assignments",
}


def _calls(node: ast.AST) -> list[ast.Call]:
    return [n for n in ast.walk(node) if isinstance(n, ast.Call)]


def _names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _func_name(call: ast.Call) -> str:
    f = call.func
    return f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""


def tables(tree: ast.AST) -> dict[str, tuple[str, bool]]:
    """Each `x = sa.Table("name", ...)`: its variable, its table name and whether its info carries a team marker,
    for the tables with a team column or a team marker."""
    out: dict[str, tuple[str, bool]] = {}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and _func_name(node.value) == "Table"
        ):
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not node.value.args:
            continue
        first = node.value.args[0]
        name = first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else target.id
        info = next((k.value for k in node.value.keywords if k.arg == "info"), None)
        marked = info is not None and any(m in ast.unparse(info) for m in MARKERS)
        columns = {
            a.args[0].value
            for a in node.value.args
            if isinstance(a, ast.Call) and a.args and isinstance(a.args[0], ast.Constant)
        }
        if marked or columns & TEAM_COLUMNS:
            out[target.id] = (str(name), marked)
    return out


def unscoped_reads(source: str, marked: set[str], where: str = "<source>") -> list[str]:
    """`where:line function table` for each function that reads a marked table and never passes that table to
    team_visible or any_team."""
    tree = ast.parse(source)
    found: list[str] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        # The function's own body only; a nested def is checked on its own.
        inner = {
            id(n)
            for d in ast.walk(fn)
            if d is not fn and isinstance(d, ast.FunctionDef | ast.AsyncFunctionDef)
            for n in ast.walk(d)
        }
        calls = [c for c in _calls(fn) if id(c) not in inner]
        # A local alias of a marked table (`t = kb_bases.c`) reads that table wherever it is selected.
        alias = {
            target.id: root
            for a in ast.walk(fn)
            if isinstance(a, ast.Assign) and id(a) not in inner
            for target in a.targets
            if isinstance(target, ast.Name)
            for root in _names(a.value) & marked
            if isinstance(a.value, ast.Name | ast.Attribute)
        }
        read: dict[str, int] = {}
        for c in calls:
            name = _func_name(c)
            if name in ("select", "select_from", "join"):
                for arg in c.args:
                    for n in _names(arg):
                        t = n if n in marked else alias.get(n)
                        if t is not None:
                            read.setdefault(t, c.lineno)
            f = c.func
            if (
                name == "select"
                and isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Name)
                and f.value.id in marked
            ):
                read.setdefault(f.value.id, c.lineno)
        scoped = {
            alias.get(a.id, a.id)
            for c in calls
            if _func_name(c) in HELPERS and c.args
            for a in [c.args[0]]
            if isinstance(a, ast.Name)
        }
        found += [f"{where}:{line} {fn.name} {t}" for t, line in sorted(read.items()) if t not in scoped]
    return found


def _sources() -> list[Path]:
    return sorted(p for pattern in SOURCES for p in ROOT.glob(pattern) if "/migrations/" not in str(p))


def _all_tables() -> dict[str, tuple[str, bool]]:
    out: dict[str, tuple[str, bool]] = {}
    for p in _sources():
        out |= tables(ast.parse(p.read_text()))
    return out


def test_every_read_of_a_team_owned_table_names_the_callers_team() -> None:
    marked = {var for var, (_, is_marked) in _all_tables().items() if is_marked}
    assert marked, "no table is marked TEAM_OWNED, so the scan checks nothing"
    found: list[str] = []
    for p in _sources():
        source = p.read_text()
        if marked & {n.id for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Name)}:
            found += unscoped_reads(source, marked, str(p.relative_to(ROOT)))
    assert found == []


def test_every_table_with_a_team_column_is_marked_or_waiting() -> None:
    every = _all_tables()
    unmarked = {name for name, is_marked in every.values() if not is_marked}
    marked = {name for name, is_marked in every.values() if is_marked}
    assert unmarked - NOT_YET_MARKED == set(), "a new team table: mark it TEAM_OWNED and read it through team_visible"
    assert NOT_YET_MARKED & marked == set(), "marked now: take it off NOT_YET_MARKED"
    assert NOT_YET_MARKED - unmarked - marked == set(), "gone: take it off NOT_YET_MARKED"


def test_the_scan_finds_a_planted_read() -> None:
    planted = """
def rows(engine):
    return engine.execute(sa.select(registry_agents))

def scoped(engine):
    return engine.execute(sa.select(registry_agents).where(team_visible(registry_agents)))

def joined(engine):
    return engine.execute(sa.select(other.c.id).select_from(other.join(registry_agents)))

def by_method(engine):
    return engine.execute(registry_agents.select())
"""
    assert unscoped_reads(planted, {"registry_agents"}) == [
        "<source>:3 rows registry_agents",
        "<source>:9 joined registry_agents",
        "<source>:12 by_method registry_agents",
    ]
