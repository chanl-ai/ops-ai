"""Only `ops_engine.starts.start` writes a run, after holding its input to the schema its trigger declares. Two
things keep it so. The write (`ops_engine.store.new_runs.write_run`) may be imported by `ops_engine.starts` alone: the
import contract `runs-written-by-the-start-entry` in `.importlinter` reads the import graph, so an alias, a helper in
another module or a re-export does not get round it. This file covers what an import contract cannot see: an insert
into the runs table itself, anywhere code lives (services, packages, plugins, scripts, examples); the writer reached
by name through the start entry, which the contract allows to import it (`from ops_engine.starts import write_run`);
and that the contract is still there with one exception.

Not covered: a write built at run time (`getattr`, `importlib`, SQL text). A review catches those.
"""

from __future__ import annotations

import ast
import configparser
from collections.abc import Callable
from pathlib import Path

import pytest

from ops_engine import starts

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
ENTRY = "packages/ops_engine/src/ops_engine/starts.py"
# The writer and its module, under every name the start entry holds them by.
WRITER_NAMES = frozenset({"write_run", "new_runs", "_new_runs"})
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


def writer_names(source: str) -> list[int]:
    """The lines of `source` that name the run writer or its module: imported, read as a name or as an attribute."""
    found: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import | ast.ImportFrom):
            module = (node.module or "") if isinstance(node, ast.ImportFrom) else ""
            parts = {x for a in node.names for x in (*a.name.split("."), a.asname)} | set(module.split("."))
            if parts & WRITER_NAMES:
                found.add(node.lineno)
        elif (isinstance(node, ast.Name) and node.id in WRITER_NAMES) or (
            isinstance(node, ast.Attribute) and node.attr in WRITER_NAMES
        ):
            found.add(node.lineno)
    return sorted(found)


def _scan(lines_of: Callable[[str], list[int]], allowed: tuple[str, ...]) -> dict[str, list[int]]:
    return {
        str(p.relative_to(ROOT)): lines
        for pattern in SOURCES
        for p in ROOT.glob(pattern)
        if ".venv" not in p.parts
        and "node_modules" not in p.parts
        and "tests" not in p.parts
        and str(p.relative_to(ROOT)) not in allowed
        and (lines := lines_of(p.read_text()))
    }


def test_nothing_but_the_run_writer_inserts_into_the_runs_table() -> None:
    found = _scan(run_inserts, (WRITER,))
    assert found == {}, f"start the run through ops_engine.starts.start, which checks its input: {found}"
    assert run_inserts((ROOT / WRITER).read_text()), "the scan no longer sees the writer's own insert"


def test_the_start_entry_does_not_hand_out_the_run_writer() -> None:
    assert not hasattr(starts, "write_run"), "ops_engine.starts must not re-export the writer"
    found = _scan(writer_names, (WRITER, ENTRY))
    assert found == {}, f"start the run through ops_engine.starts.start, which checks its input: {found}"
    assert writer_names((ROOT / ENTRY).read_text()), "the scan no longer sees the start entry's own use"


@pytest.mark.parametrize(
    "bypass",
    [
        "from ops_engine.starts import write_run\n",
        "from ops_engine import starts\nrun = starts._new_runs.write_run\n",
        "import ops_engine.starts as s\nw = s.write_run\n",
        "from ops_engine.starts import _new_runs as rows\n",
    ],
    ids=["the name from the entry", "the entry's private module", "an attribute of the entry", "an alias"],
)
def test_the_run_writer_named_through_the_start_entry_is_caught(bypass: str) -> None:
    assert writer_names(bypass), bypass
    assert not writer_names("from ops_engine.starts import start\nrun = await start(runs, stored, new, registry)\n")


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
