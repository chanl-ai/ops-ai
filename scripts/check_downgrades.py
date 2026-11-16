"""Refuse a migration whose downgrade does nothing.

deploy/database/tests/test_runtime_logins.py migrates every chain down and back up, so a revision with an empty
downgrade leaves its columns behind and the second upgrade fails ("already exists"). Three revisions did this on
10-31 (tools 0048, 0049, 0050) and each held QA red for about an hour. This check runs at commit time on the staged
migration files only, so it catches the next one before HEAD goes red.

  python3 scripts/check_downgrades.py --root <tree> <path> [<path> ...]
  python3 scripts/check_downgrades.py --all [--root <tree>] [--waiting <file>]

`--all` reads every migration under services/ and packages/ (it is the check `make checks` runs). The ones that held an
empty downgrade before this check ran are in scripts/downgrades-waiting.txt; the list only shrinks: a new empty
downgrade fails, and so does a listed migration that now undoes its upgrade, until it is taken off the list.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def empty_downgrade(source: str) -> bool:
    """True when `downgrade()` holds nothing but a docstring, `pass` or `...`."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == "downgrade":
            body = [
                s
                for s in node.body
                if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))  # docstring or ...
            ]
            return all(isinstance(s, ast.Pass) for s in body)
    return False  # no downgrade at all is alembic's own error, not this check's


def check_all(root: Path, waiting_file: Path) -> int:
    listed = {line.strip() for line in waiting_file.read_text().splitlines() if line.strip()}
    found = {
        str(p.relative_to(root))
        for top in ("services", "packages")
        for p in (root / top).glob("*/migrations/versions/*.py")
        if empty_downgrade(p.read_text())
    }
    for path in sorted(found - listed):
        print(f"check-downgrades: {path}: downgrade() does nothing; undo exactly what upgrade() did")
    for path in sorted(listed - found):
        print(f"check-downgrades: {path}: its downgrade undoes its upgrade now; remove it from {waiting_file.name}")
    return 1 if found != listed else 0


def main(argv: list[str]) -> int:
    root = Path(argv[argv.index("--root") + 1]) if "--root" in argv else Path(".")
    if "--all" in argv:
        waiting = (
            Path(argv[argv.index("--waiting") + 1]) if "--waiting" in argv else Path("scripts/downgrades-waiting.txt")
        )
        return check_all(root, waiting if waiting.is_absolute() else root / waiting)
    paths = [p for p in argv if p.endswith(".py") and "/migrations/versions/" in p and p != "--root"]
    bad = [p for p in paths if (root / p).is_file() and empty_downgrade((root / p).read_text())]
    for p in bad:
        print(f"check-downgrades: {p}: downgrade() does nothing; undo exactly what upgrade() did")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
