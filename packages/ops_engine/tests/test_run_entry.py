"""Only `ops_engine.starts.start` writes a run, after holding its input to the schema its trigger declares. Two
things keep it so. The write (`ops_engine.store.new_runs.write_run`) may be imported by `ops_engine.starts` alone: the
import contract `runs-written-by-the-start-entry` in `.importlinter` reads the import graph, so an alias, a helper in
another module or a re-export does not get round it. This file covers what an import contract cannot see: an insert
into the runs table itself, anywhere code lives (services, packages, plugins, scripts, examples), and that the
contract is still there with one exception.

Not covered: a write built at run time (`getattr`, `importlib`, SQL text). A review catches those.
"""

from __future__ import annotations

import ast
import configparser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SOURCES = (
    "services/*/src/**/*.py",
    "packages/*/src/**/*.py",
    "builtin-plugins/**/*.py",
    "plugins/**/*.py",
    "scripts/**/*.py",
    "examples/**/*.py",
)
WRITER = "packages/ops_engine/src/ops_engine/store/new_runs.py"
TABLE = "engine_runs"


def run_inserts(source: str) -> list[int]:
    """The lines of `source` that insert into the runs table: `engine_runs.insert()` or `insert(engine_runs)`, under
    the table's own name, an import alias, a name assigned from it, or as an attribute (`tables.engine_runs`)."""
    tree = ast.parse(source)
    names = {TABLE}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names |= {a.asname for a in node.names if a.name == TABLE and a.asname}

    def is_table(node: ast.AST) -> bool:
        return (isinstance(node, ast.Name) and node.id in names) or (
            isinstance(node, ast.Attribute) and node.attr == TABLE
        )

    for _ in range(2):
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and is_table(node.value):
                names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    found: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        called = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
        on_table = isinstance(f, ast.Attribute) and is_table(f.value)
        if called == "insert" and (on_table or any(is_table(a) for a in node.args)):
            found.append(node.lineno)
    return sorted(found)


def test_nothing_but_the_run_writer_inserts_into_the_runs_table() -> None:
    found = {
        str(p.relative_to(ROOT)): lines
        for pattern in SOURCES
        for p in ROOT.glob(pattern)
        if ".venv" not in p.parts
        and "node_modules" not in p.parts
        and "tests" not in p.parts
        and str(p.relative_to(ROOT)) != WRITER
        and (lines := run_inserts(p.read_text()))
    }
    assert found == {}, f"start the run through ops_engine.starts.start, which checks its input: {found}"
    assert run_inserts((ROOT / WRITER).read_text()), "the scan no longer sees the writer's own insert"


@pytest.mark.parametrize(
    "bypass",
    [
        "from ops_engine.store.tables import engine_runs\nq = engine_runs.insert().values(id='r')\n",
        "from ops_engine.store.tables import engine_runs as r\nq = r.insert()\n",
        "import sqlalchemy as sa\nfrom ops_engine.store import tables\nq = sa.insert(tables.engine_runs)\n",
        "from ops_engine.store.tables import engine_runs\nt = engine_runs\nq = t.insert()\n",
    ],
    ids=["the table", "an import alias", "insert(table) through the module", "a name assigned from it"],
)
def test_an_insert_into_the_runs_table_is_caught(bypass: str) -> None:
    assert run_inserts(bypass), bypass
    assert not run_inserts("from x import engine_work\nq = engine_work.insert()\n"), "another table's insert"


def test_the_run_writer_is_importable_by_the_start_entry_alone() -> None:
    """The contract itself is run by `uv run lint-imports` (make python-verify and the commit gate). This holds its
    shape: every root package is a source, and the start entry is the one exception."""
    config = configparser.ConfigParser()
    config.read(ROOT / ".importlinter")
    contract = config["importlinter:contract:runs-written-by-the-start-entry"]
    roots = set(config["importlinter"]["root_packages"].split())
    assert set(contract["source_modules"].split()) == roots
    assert contract["forbidden_modules"].split() == ["ops_engine.store.new_runs"]
    ignored = [line.strip() for line in contract["ignore_imports"].splitlines() if line.strip()]
    assert [i for i in ignored if not i.startswith("#")] == ["ops_engine.starts -> ops_engine.store.new_runs"]
