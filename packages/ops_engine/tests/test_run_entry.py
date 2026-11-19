"""Only `ops_engine.starts.start` writes a run. It holds the run's input to the schema its trigger declares, so a
start path that calls `RunStore.create` itself starts runs whose required fields and types nobody checked, which is
how text reached a number compare and sent runs down the wrong branch.

The scan is of source, like ops_store's test_team_reads.py: a write is `.create(...)` on a `RunStore(...)`, on a name
or attribute a `RunStore` is bound to (an annotation, an assignment), or on the result of a function annotated to
return one. Names are matched across the whole file, so the scan reports too much before it reports too little.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SOURCES = ("services/*/src/**/*.py", "packages/*/src/**/*.py")
ENTRY = "packages/ops_engine/src/ops_engine/starts.py"
STORE = "RunStore"


def _name(node: ast.AST) -> str | None:
    """The identifier a store is held under: `runs`, or `runs` of `self.runs`."""
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None


def _is_store(node: ast.AST, held: set[str], makers: set[str]) -> bool:
    if isinstance(node, ast.Call):
        return _name(node.func) in {STORE, *makers}
    return _name(node) in held


def run_writes(source: str) -> list[int]:
    """The lines of `source` that write a run through `RunStore.create`."""
    tree = ast.parse(source)
    held: set[str] = set()
    makers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and node.annotation is not None and STORE in ast.unparse(node.annotation):
            held.add(node.arg)
        elif isinstance(node, ast.AnnAssign) and STORE in ast.unparse(node.annotation) and (n := _name(node.target)):
            held.add(n)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.returns is not None:
            makers.update({node.name} if STORE in ast.unparse(node.returns) else ())
    # `runs = RunStore(tx)` and `self.runs, self.definitions = runs, definitions`: twice, so a name bound from a name
    # bound later in the file is still found.
    for _ in range(2):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                pairs = (
                    zip(target.elts, node.value.elts, strict=False)
                    if isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple)
                    else [(target, node.value)]
                )
                for to, value in pairs:
                    if _is_store(value, held, makers) and (n := _name(to)):
                        held.add(n)
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create"
        and _is_store(node.func.value, held, makers)
    )


def test_only_the_start_entry_writes_a_run() -> None:
    found = {
        str(p.relative_to(ROOT)): lines
        for pattern in SOURCES
        for p in ROOT.glob(pattern)
        if str(p.relative_to(ROOT)) != ENTRY and (lines := run_writes(p.read_text()))
    }
    assert found == {}, f"start the run through ops_engine.starts.start, which checks its input: {found}"
    assert run_writes((ROOT / ENTRY).read_text()), "the scan no longer sees the entry's own write"


@pytest.mark.parametrize(
    "bypass",
    [
        "from ops_engine.store import RunStore\nasync def start(tx, row):\n    return await RunStore(tx).create(row)\n",
        "async def start(runs: RunStore, row):\n    return await runs.create(row)\n",
        "class Starts:\n    def __init__(self, runs: RunStore):\n        self.runs, self.n = runs, 0\n"
        "    async def start(self, row):\n        return await self.runs.create(row)\n",
        "def runs(rt) -> RunStore: ...\nasync def start(rt, row):\n    return await runs(rt).create(row)\n",
    ],
    ids=["a new store", "a store passed in", "a store kept on self", "a store from a helper"],
)
def test_a_start_path_that_writes_the_run_itself_is_caught(bypass: str) -> None:
    assert run_writes(bypass), bypass
    assert not run_writes("async def share(links, row):\n    return await links.create(row)\n"), (
        "another store's create"
    )
