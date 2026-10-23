"""A loop a service starts and nobody listed (c-516): it runs unseen, so a stuck one shows up nowhere. Every function
in a service or package that waits in a loop must be the listed runner, a listed process's own loop, or named in
`EXEMPT` with a reason. Tests are not scanned."""

from __future__ import annotations

import ast
import fnmatch
from pathlib import Path

from ops_store.background import BY_KEY, EXEMPT, LOOPS

ROOT = Path(__file__).resolve().parents[3]
SOURCES = sorted(p for p in (*ROOT.glob("packages/*/src"), *ROOT.glob("services/*/src")) if p.is_dir())


def _waits(node: ast.AST) -> bool:
    """A call that pauses the loop: asyncio.sleep, or asyncio.wait_for (a stop event with a timeout)."""
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in ("sleep", "wait_for"):
            return True
    return False


def waiting_loops() -> list[str]:
    """Every function whose body holds a `while` loop that pauses, by dotted name (module.Class.function)."""
    found: list[str] = []
    for src in SOURCES:
        for path in src.rglob("*.py"):
            parts = path.relative_to(src).with_suffix("").parts
            module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
            tree = ast.parse(path.read_text())

            def visit(node: ast.AST, prefix: str) -> None:
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, ast.ClassDef):
                        visit(child, f"{prefix}.{child.name}")
                    elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                        name = f"{prefix}.{child.name}"
                        loops = [n for n in ast.walk(child) if isinstance(n, ast.While)]
                        if any(_waits(loop) for loop in loops):
                            found.append(name)
                        visit(child, name)

            visit(tree, module)
    return found


def test_every_waiting_loop_is_listed_or_exempt() -> None:
    unlisted = [
        f for f in waiting_loops() if f not in LOOPS and not any(fnmatch.fnmatchcase(f, pattern) for pattern in EXEMPT)
    ]
    assert unlisted == [], (
        "a loop runs that is not on ops_store.background (list its process in PROCESSES and start it through "
        "background.run, or name it in LOOPS or EXEMPT with a reason):\n" + "\n".join(unlisted)
    )


def test_every_listed_loop_names_a_listed_process_and_still_exists() -> None:
    loops = set(waiting_loops())
    assert {k for k, process in LOOPS.items() if process not in BY_KEY} == set()
    assert {k for k in LOOPS if k not in loops} == set(), "a listed loop no longer exists; take it off LOOPS"
